"""Jetson 本机独立 SSH 服务及设备侧 SSH 任务执行器。"""

import base64
import binascii
import configparser
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import quote, urlsplit
from zipimport import zipimporter

import requests


ROOT = Path('/etc/device-agent/ssh-management')
KEY_FILE = Path('/etc/device-agent-ssh.keys')
UNIT_DIR = Path('/etc/systemd/system')
SSHD = '/usr/sbin/sshd'
SSHD_UNIT = 'device-agent-managed-ssh.service'
ROLLBACK_UNIT = 'device-agent-ssh-rollback.service'
ROLLBACK_TIMER = 'device-agent-ssh-rollback.timer'
DEVICE_ID_FILE = Path('/etc/device-id')
FRPC = Path('/etc/frp/frpc.ini')
FRPC_UNIT = 'frpc.service'
SERVER_CA = ROOT / 'server-ca.crt'
MANAGED_PORT = 2222
WINDOW = 300
FINGERPRINT = re.compile(r'SHA256:[A-Za-z0-9+/]{43}')


class SshManagementError(ValueError):
    """可安全返回给平台、不包含命令输出或私密配置的操作错误。"""


def run(*args, timeout=12):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)


def systemctl(*args):
    return run('/usr/bin/systemctl', *args)


def atomic_write(path, data, mode=0o600):
    """原子替换固定路径，文件在可见前已经拥有最终权限。"""
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data.encode('utf-8') if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def root_owned_path(path, directory=False, public_readable=False):
    info = path.lstat()
    valid_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not valid_type(info.st_mode) or info.st_uid != 0 or info.st_mode & (0o022 if public_readable else 0o077):
        raise SshManagementError('纳管文件归属或权限错误，或路径为符号链接')


def public_key(line):
    if not isinstance(line, str) or not line.isprintable() or len(line) > 512:
        raise SshManagementError('公钥格式不正确')
    fields = line.split(maxsplit=2)
    try:
        if len(fields) >= 2 and fields[0] == 'ssh-ed25519':
            wire = base64.b64decode(fields[1], validate=True)
            if len(wire) == 51 and wire.startswith(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 '):
                digest = base64.b64encode(hashlib.sha256(wire).digest()).decode().rstrip('=')
                return 'SHA256:' + digest, ' '.join(fields)
    except binascii.Error:
        pass
    raise SshManagementError('只接受单行 Ed25519 公钥')


class SshManagement:
    def __init__(self, device_id, *, load_enrollment=True):
        self.device_id = device_id
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', device_id or ''):
            raise SshManagementError('设备编号格式不支持 SSH 纳管')
        self.settings_path = ROOT / 'enrollment.json'
        self.state_path = ROOT / 'state.json'
        root_owned_path(ROOT, directory=True)
        self.base_url = ''
        self.credential = ''
        self.account = ''
        self.recovery_verified = False
        self.verify = str(SERVER_CA)
        # 专用服务必须在 Agent 不运行时仍能读取回退状态。
        self.proxy_section = f'{device_id}_ssh'
        if load_enrollment and self.settings_path.exists():
            root_owned_path(self.settings_path)
            enrollment = json.loads(self.settings_path.read_text(encoding='utf-8'))
            cloud_server = enrollment.get('server_url')
            url = urlsplit(cloud_server if isinstance(cloud_server, str) else '')
            if (url.scheme != 'https' or not url.hostname or url.username or url.password
                    or url.query or url.fragment):
                raise SshManagementError('SSH 管理 Agent 必须配置 HTTPS 平台地址')
            root_owned_path(SERVER_CA, public_readable=True)
            self.account = enrollment.get('account')
            self.credential = enrollment.get('credential')
            if not isinstance(self.account, str) or not re.fullmatch(
                    r'[a-z_][a-z0-9_-]{0,30}', self.account):
                raise SshManagementError('本机运维账号配置错误')
            if self.account == 'root':
                raise SshManagementError('SSH 纳管禁止使用 root 账号')
            if not isinstance(self.credential, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', self.credential):
                raise SshManagementError('设备 SSH 凭据无效')
            self.recovery_verified = enrollment.get('independent_recovery_verified') is True
            self.base_url = cloud_server.rstrip('/') + '/agent/ssh-management/' + quote(device_id, safe='')

    @contextmanager
    def lock(self):
        """序列化写入、FRP 常规同步和独立回退。"""
        import fcntl

        fd = os.open(ROOT / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def load_state(self):
        if not self.state_path.exists():
            return {'mode': 'legacy', 'verified': []}
        root_owned_path(self.state_path)
        state = json.loads(self.state_path.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or state.get('mode') not in ('legacy', 'pending', 'active', 'rolled_back'):
            raise SshManagementError('SSH 纳管状态文件无效，拒绝更改 FRP')
        return state

    def save_state(self, state):
        atomic_write(self.state_path, json.dumps(state))

    def config(self):
        parser = configparser.RawConfigParser(strict=True)
        with FRPC.open(encoding='utf-8') as handle:
            parser.read_file(handle)
        return parser

    def validate_frpc(self, parser, port):
        if parser.defaults() or not parser.has_section('common') or parser['common'].get('includes'):
            raise SshManagementError('不支持带默认继承或外部包含的 FRP 配置')
        if self.proxy_section not in parser:
            raise SshManagementError('未找到该设备的 FRP SSH 隧道')
        section = parser[self.proxy_section]
        if (
            section.get('type', 'tcp') != 'tcp'
            or section.get('local_ip') != '127.0.0.1'
            or section.get('local_port') != str(port)
            or section.get('plugin')
        ):
            raise SshManagementError('FRP SSH 不是预期的本机 TCP 映射')
        for name in parser.sections():
            if name not in ('common', self.proxy_section):
                other = parser[name]
                local_port = other.get('local_port', '').strip()
                if (local_port and (not local_port.isdecimal() or int(local_port) in (22, MANAGED_PORT))) or other.get('plugin'):
                    raise SshManagementError('存在其它 SSH 映射或自定义 FRP 插件，拒绝切换')

    def render_cloud_config(self, ini):
        """保留远程仅公钥目标，避免常规 FRP 同步把目标退回现场 22。"""
        if self.load_state()['mode'] not in ('pending', 'active'):
            return ini
        parser = configparser.RawConfigParser()
        parser.read_string(ini)
        if self.proxy_section not in parser:
            raise SshManagementError('缺少已纳管的 FRP SSH 隧道')
        parser[self.proxy_section]['local_port'] = str(MANAGED_PORT)
        self.validate_frpc(parser, MANAGED_PORT)
        result = StringIO()
        parser.write(result)
        return result.getvalue()

    def managed_keys(self):
        path = KEY_FILE
        if not path.exists():
            return {}
        root_owned_path(path, public_readable=True)
        return dict(public_key(line) for line in path.read_text(encoding='utf-8').splitlines() if line)

    def store_keys(self, keys):
        # sshd 以目标用户读取公钥；文件无秘密，但目录仍须允许该用户穿越。
        atomic_write(KEY_FILE, '\n'.join(keys.values()) + '\n', 0o644)

    def verify_account(self):
        import pwd

        try:
            entry = pwd.getpwnam(self.account)
        except KeyError:
            raise SshManagementError('本机运维账号不存在') from None
        if entry.pw_uid == 0 or not entry.pw_shell or entry.pw_shell.endswith(('nologin', '/false')):
            raise SshManagementError('只支持可登录的非 root 运维账号')

    def effective_config(self, *extra):
        result = run(SSHD, '-T', *extra, '-C', f'user={self.account},host=localhost,addr=127.0.0.1')
        return dict(line.split(maxsplit=1) for line in result.stdout.splitlines() if ' ' in line)

    def sshd_ready(self):
        path = ROOT / 'sshd_config'
        properties = dict(
            line.split('=', 1) for line in systemctl(
                'show', '-p', 'FragmentPath,DropInPaths,MainPID', SSHD_UNIT,
            ).stdout.splitlines() if '=' in line
        )
        if properties.get('FragmentPath') != str(UNIT_DIR / SSHD_UNIT) or properties.get('DropInPaths'):
            raise SshManagementError('独立 SSH 服务位置不符或存在额外的 systemd 覆盖')
        run(SSHD, '-t', '-f', str(path))
        effective = self.effective_config('-f', str(path))
        if (
            effective.get('passwordauthentication') != 'no'
            or effective.get('kbdinteractiveauthentication') != 'no'
            or effective.get('pubkeyauthentication') != 'yes'
            or effective.get('authenticationmethods') != 'publickey'
            or effective.get('permitrootlogin') != 'no'
            or effective.get('authorizedkeysfile') != str(KEY_FILE)
            or effective.get('allowusers') != self.account
            or effective.get('listenaddress') != f'127.0.0.1:{MANAGED_PORT}'
            or effective.get('maxauthtries') != '3'
            or effective.get('logingracetime') != '20'
        ):
            raise SshManagementError('独立 SSH 服务的生效设置不符合仅公钥策略')
        pid = properties.get('MainPID', '')
        listeners = run('/usr/bin/ss', '-Hlnpt', f'sport = :{MANAGED_PORT}').stdout.splitlines()
        if (
            not pid.isdecimal() or pid == '0' or len(listeners) != 1
            or listeners[0].split()[3] != f'127.0.0.1:{MANAGED_PORT}'
            or f'pid={pid},' not in listeners[0]
        ):
            raise SshManagementError('未确认独立 SSH 服务独占本机回环端口')

    def start_sshd(self):
        self.verify_account()
        host_key = '/etc/ssh/ssh_host_ed25519_key'
        if not Path(host_key).is_file() or f'hostkey {host_key}' not in run(SSHD, '-T').stdout.splitlines():
            raise SshManagementError('未找到现场 SSH 使用的 Ed25519 主机密钥')
        config = (
            f'Port {MANAGED_PORT}\nAddressFamily inet\nListenAddress 127.0.0.1\n'
            'HostKey /etc/ssh/ssh_host_ed25519_key\n'
            f'AuthorizedKeysFile {KEY_FILE}\nAllowUsers {self.account}\n'
            'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n'
            'PubkeyAuthentication yes\nAuthenticationMethods publickey\nUsePAM yes\n'
            'MaxAuthTries 3\nLoginGraceTime 20\nMaxStartups 10:30:30\n'
            'PermitEmptyPasswords no\nDisableForwarding yes\nPermitUserEnvironment no\nLogLevel VERBOSE\n'
            'Subsystem sftp internal-sftp\n'
        )
        unit = (
            '[Unit]\nDescription=Device Agent dedicated public-key SSH\nAfter=ssh.service\n'
            '[Service]\nType=simple\nExecStartPre=/usr/sbin/sshd -t -f ' + str(ROOT / 'sshd_config') + '\n'
            'ExecStart=/usr/sbin/sshd -D -e -f ' + str(ROOT / 'sshd_config') + '\n'
            'Restart=on-failure\nRestartSec=15\nTimeoutStartSec=15\n'
            '[Install]\nWantedBy=multi-user.target\n'
        )
        unit_path = UNIT_DIR / SSHD_UNIT
        if unit_path.is_symlink() or (unit_path.exists() and unit_path.read_text(encoding='utf-8') != unit):
            raise SshManagementError('同名 SSH 服务不属于本功能')
        if run('/usr/bin/ss', '-Hlnpt', f'sport = :{MANAGED_PORT}').stdout:
            if not unit_path.is_file() or (ROOT / 'sshd_config').read_text(encoding='utf-8') != config:
                raise SshManagementError('回环 SSH 端口已占用或现有配置改变')
            self.sshd_ready()
            return
        if not unit_path.exists():
            atomic_write(unit_path, unit, 0o644)
        atomic_write(ROOT / 'sshd_config', config)
        run(SSHD, '-t', '-f', str(ROOT / 'sshd_config'))
        systemctl('daemon-reload')
        systemctl('enable', '--now', SSHD_UNIT)
        for attempt in range(10):
            try:
                self.sshd_ready()
                break
            except SshManagementError:
                if attempt == 9:
                    raise
                time.sleep(0.2)

    def arm_rollback(self, until):
        script = Path(__loader__.archive if isinstance(__loader__, zipimporter) else __file__).resolve()
        # ExecStart 参数不来自平台任务；禁止 systemd 字符串展开误解释本机路径。
        if not re.fullmatch(r'/[A-Za-z0-9_/.-]+', str(script)):
            raise SshManagementError('SSH 管理模块路径无法用于回退服务')
        when = datetime.fromtimestamp(until, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        files = {
            ROLLBACK_UNIT: (
                '[Unit]\nDescription=Recover unconfirmed managed SSH cutover\n'
                f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {script} rollback {self.device_id}\n'
                'TimeoutStartSec=60\nRestart=on-failure\nRestartSec=15\n'
            ),
            ROLLBACK_TIMER: (
                '[Unit]\nDescription=Rollback deadline for device SSH\n'
                f'[Timer]\nOnCalendar={when}\nPersistent=yes\nAccuracySec=1s\n'
                '[Install]\nWantedBy=timers.target\n'
            ),
        }
        for name, content in files.items():
            path = UNIT_DIR / name
            marker = '# Managed by Device Agent SSH\n'
            if path.is_symlink() or (path.exists() and not path.read_text(encoding='utf-8').startswith(marker)):
                raise SshManagementError('同名回退服务不属于本功能')
            atomic_write(path, marker + content, 0o644)
        systemctl('daemon-reload')
        systemctl('enable', ROLLBACK_TIMER)
        systemctl('restart', ROLLBACK_TIMER)
        systemctl('is-active', '--quiet', ROLLBACK_TIMER)

    def rollback(self, state, restart=None):
        if state['mode'] != 'pending':
            return
        backup = ROOT / 'frpc.previous'
        root_owned_path(backup)
        saved = configparser.RawConfigParser()
        saved.read_string(backup.read_text(encoding='utf-8'))
        self.validate_frpc(saved, 22)
        current = self.config()
        if current.has_section(self.proxy_section):
            # 保留试登期间合法变化，只撤回该隧道的目标端口。
            current[self.proxy_section]['local_port'] = '22'
            self.validate_frpc(current, 22)
            result = StringIO()
            current.write(result)
            atomic_write(FRPC, result.getvalue())
            if restart is True or (restart is None and not state.get('frpc_disabled')):
                systemctl('restart', FRPC_UNIT)
                if not self.frpc_running():
                    raise SshManagementError('切回旧 SSH 入口后，FRP 未正常运行')
        state.update(mode='rolled_back', pending=None)
        self.save_state(state)

    def note_frp_enabled(self, enabled):
        state = self.load_state()
        if state['mode'] == 'pending' and state.get('frpc_disabled', False) == enabled:
            state['frpc_disabled'] = not enabled
            self.save_state(state)

    def frpc_running(self):
        return systemctl('show', '-p', 'ActiveState', '--value', FRPC_UNIT).stdout.strip() == 'active'

    def login_observed(self, since, fingerprint):
        lines = run(
            '/usr/bin/journalctl', '-u', SSHD_UNIT, '--since', f'@{int(since)}',
            '--no-pager', '-o', 'json', '-n', '150',
        ).stdout.splitlines()
        pattern = re.compile(
            rf'^Accepted publickey for {re.escape(self.account)} from 127\.0\.0\.1 port \d+ '
            rf'ssh2: ED25519 {re.escape(fingerprint)}(?:\s|$)'
        )
        for line in lines:
            entry = json.loads(line)
            if (
                entry.get('_UID') == '0'
                and entry.get('_SYSTEMD_UNIT') == SSHD_UNIT
                and int(entry.get('__REALTIME_TIMESTAMP', '0')) >= int(since * 1_000_000)
                and pattern.match(entry.get('MESSAGE', ''))
            ):
                return True
        return False

    def status(self):
        state = self.load_state()
        pending = state.get('pending')
        keys = self.managed_keys()
        status = {
            'account': self.account, 'mode': state['mode'], 'local_password': 'unknown', 'frp_target': None,
            'independent_recovery_verified': self.recovery_verified,
            'remote_publickey_only': False, 'host_fingerprints': [],
            'keys': [{'fingerprint': fp, 'verified': fp in state['verified']} for fp in keys],
            'pending_fingerprint': pending['fingerprint'] if pending else None,
            'pending_until': datetime.fromtimestamp(pending['until'], timezone.utc).isoformat() if pending else None,
            'login_observed': False, 'error': '',
        }
        try:
            self.verify_account()
            local = self.effective_config()
            status['local_password'] = 'enabled' if (
                local.get('passwordauthentication') == 'yes' or local.get('kbdinteractiveauthentication') == 'yes'
            ) else 'disabled'
            line = Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text(encoding='utf-8').strip()
            status['host_fingerprints'] = [public_key(line)[0]]
            parser = self.config()
            if self.frpc_running():
                status['frp_target'] = parser.getint(self.proxy_section, 'local_port')
            if state['mode'] in ('pending', 'active'):
                self.sshd_ready()
                self.validate_frpc(parser, MANAGED_PORT)
                status['remote_publickey_only'] = status['frp_target'] == MANAGED_PORT
                if pending and pending['since'] and time.time() < pending['until']:
                    status['login_observed'] = self.login_observed(pending['since'], pending['fingerprint'])
        except SshManagementError as exc:
            status['error'] = str(exc)
        except (OSError, ValueError, configparser.Error, subprocess.SubprocessError):
            status['error'] = '无法验证 SSH 或 FRP 运行状态；请核对设备端配置及服务'
        return status

    def execute(self, operation, payload):
        if not isinstance(payload, dict):
            raise SshManagementError('SSH 任务参数无效')
        state = self.load_state()
        fp = payload.get('fingerprint')
        if not isinstance(fp, str) or not FINGERPRINT.fullmatch(fp):
            raise SshManagementError('无效的公钥指纹')
        pending = state.get('pending')
        keys = self.managed_keys()
        if pending and operation != 'confirm':
            raise SshManagementError('当前已有待确认的 SSH 操作')
        if operation == 'add_key':
            actual, line = public_key(payload.get('public_key'))
            self.verify_account()
            if actual != fp or (fp not in keys and len(keys) >= 32):
                raise SshManagementError('公钥指纹不匹配或数量超限')
            self.store_keys({**keys, fp: line})
            return
        if fp not in keys:
            raise SshManagementError('该公钥尚未添加到设备')
        if operation in ('activate', 'verify_key', 'confirm'):
            parser = self.config()
            self.validate_frpc(parser, 22 if operation == 'activate' else MANAGED_PORT)
            if parser.getint(self.proxy_section, 'remote_port') != payload.get('external_port'):
                raise SshManagementError('设备实际 FRP 外部端口与平台分配不一致')
        if operation == 'activate':
            if state['mode'] == 'active' or not self.recovery_verified:
                raise SshManagementError('远程已启用仅公钥，或未通过现场独立恢复通道预检')
            self.activate(state, fp)
        elif operation == 'verify_key':
            if state['mode'] != 'active':
                raise SshManagementError('仅公钥服务尚未启用')
            self.sshd_ready()
            self.validate_frpc(self.config(), MANAGED_PORT)
            if not self.frpc_running():
                raise SshManagementError('FRP SSH 隧道未运行')
            now = time.time()
            state['pending'] = {'fingerprint': fp, 'since': now, 'until': now + WINDOW}
            self.save_state(state)
        elif operation == 'confirm':
            if (
                not pending or pending['fingerprint'] != fp or not pending['since']
                or time.time() >= pending['until'] or not self.login_observed(pending['since'], fp)
            ):
                raise SshManagementError('未观察到窗口内指定公钥的登录，本次未确认')
            self.sshd_ready()
            self.validate_frpc(self.config(), MANAGED_PORT)
            if not self.frpc_running():
                raise SshManagementError('FRP SSH 隧道未运行')
            state.update(mode='active', pending=None, verified=sorted(set([*state['verified'], fp])))
            self.save_state(state)
        elif operation == 'remove_key':
            if state['mode'] != 'active' or not (set(state['verified']) & (keys.keys() - {fp})):
                raise SshManagementError('必须保留至少一把已实测登录的公钥')
            self.sshd_ready()
            state['verified'] = [key for key in state['verified'] if key != fp]
            self.save_state(state)
            del keys[fp]
            self.store_keys(keys)
        else:
            raise SshManagementError('不支持的 SSH 操作')

    def activate(self, state, fp):
        parser = self.config()
        self.validate_frpc(parser, 22)
        config_command = systemctl('show', '-p', 'ExecStart', '--value', FRPC_UNIT).stdout
        if not self.frpc_running() or not re.search(rf'\s-c\s+{re.escape(str(FRPC))}(?:\s|$)', config_command):
            raise SshManagementError('FRP 未运行或未使用标准配置文件')
        self.start_sshd()
        atomic_write(ROOT / 'frpc.previous', FRPC.read_bytes())
        until = int(time.time()) + WINDOW
        self.arm_rollback(until)
        state.update(mode='pending', pending={'fingerprint': fp, 'until': until, 'since': None},
                     frpc_disabled=False)
        self.save_state(state)
        try:
            atomic_write(FRPC, self.render_cloud_config(FRPC.read_text(encoding='utf-8')))
            systemctl('restart', FRPC_UNIT)
            if not self.frpc_running():
                raise SshManagementError('FRP 切换未通过服务状态校验')
            state['pending']['since'] = time.time()
            self.save_state(state)
        except (OSError, ValueError, SshManagementError, configparser.Error, subprocess.SubprocessError):
            self.rollback(state, restart=True)
            raise

    def poll(self):
        """通过固定私有 CA 的 HTTPS 通道领取任务并补发回执。"""
        if not self.base_url or not self.credential:
            raise SshManagementError('缺少 SSH 纳管凭据或 HTTPS 平台地址')
        with self.lock():
            state = self.load_state()
            pending = state.get('pending')
            if pending and pending['until'] <= time.time():
                if state['mode'] == 'pending':
                    self.rollback(state)
                else:
                    state['pending'] = None
                    self.save_state(state)
            snapshot = self.status()
        headers = {'Authorization': 'Bearer ' + self.credential}
        with requests.Session() as session:
            session.trust_env = False
            session.headers.update(headers)
            session.verify = self.verify
            receipt_path = ROOT / 'receipt.json'
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                response = session.post(self.base_url + '/receipt/', json=receipt, timeout=(3, 4), allow_redirects=False)
                if response.status_code not in (204, 404, 409):
                    raise SshManagementError(f'SSH 回执未接收（HTTP {response.status_code}）')
                receipt_path.unlink()
            response = session.post(self.base_url + '/poll/', json=snapshot, timeout=(3, 4), allow_redirects=False)
            if response.status_code != 200:
                raise SshManagementError(f'SSH 任务通道未就绪（HTTP {response.status_code}）')
            body = response.json()
            if not isinstance(body, dict) or 'task' not in body:
                raise SshManagementError('任务响应格式无效')
            task = body['task']
        if task is None:
            return
        if not isinstance(task, dict):
            raise SshManagementError('任务响应格式无效')
        task_id = task.get('id')
        if not isinstance(task_id, str) or not re.fullmatch(r'[a-f0-9]{32}', task_id):
            raise SshManagementError('任务编号无效')
        receipt = {'id': task_id, 'ok': False, 'error': ''}
        with self.lock():
            last_task = ROOT / 'last-task'
            if last_task.exists() and last_task.read_text(encoding='ascii') == task_id:
                raise SshManagementError('拒绝重复执行已领取的 SSH 任务')
            atomic_write(last_task, task_id)
            try:
                expires = datetime.fromisoformat(task['expires_at'].replace('Z', '+00:00'))
                if expires <= datetime.now(timezone.utc):
                    raise SshManagementError('拒绝执行过期 SSH 任务')
                self.execute(task['operation'], task['payload'])
                receipt['ok'] = True
            except SshManagementError as exc:
                receipt['error'] = str(exc)
            except (OSError, KeyError, ValueError, configparser.Error, subprocess.SubprocessError):
                receipt['error'] = '设备端操作失败；请核对本机 SSH 与回退服务状态'
            atomic_write(receipt_path, json.dumps(receipt))

    def run_poll_loop(self, logger):
        """将 SSH 管理 I/O 与原 Agent 心跳及部署任务隔离。"""
        while True:
            try:
                self.poll()
            except SshManagementError as exc:
                logger.warning('SSH 管理: %s', exc)
            except (requests.RequestException, OSError, ValueError, TypeError,
                    configparser.Error, subprocess.SubprocessError) as exc:
                logger.warning('SSH 管理轮询失败 (%s)', type(exc).__name__)
            time.sleep(8)


def enroll(ca_path, *, recovery_verified=False):
    """从标准输入读取纳管文件，验证本机身份、账号及 TLS 后写入首次纳管配置。"""
    if os.geteuid() != 0:
        raise SshManagementError('需要在目标设备的可信 root 终端执行纳管')
    root_owned_path(DEVICE_ID_FILE, public_readable=True)
    device_id = DEVICE_ID_FILE.read_text(encoding='ascii').strip()
    raw = sys.stdin.read(8193)
    if len(raw) > 8192:
        raise SshManagementError('纳管文件超出大小限制')
    enrollment = json.loads(raw)
    if not isinstance(enrollment, dict) or enrollment.get('device_id') != device_id:
        raise SshManagementError('纳管文件的设备 ID 与本机不一致')
    if set(enrollment) - {'device_id', 'account', 'credential', 'server_url', 'independent_recovery_verified'}:
        raise SshManagementError('纳管文件含不支持的字段')

    with ca_path.open('rb') as handle:
        ca_data = handle.read(32769)
    if len(ca_data) > 32768 or b'PRIVATE KEY' in ca_data or b'-----BEGIN CERTIFICATE-----' not in ca_data:
        raise SshManagementError('请输入已核对指纹的公开平台 CA 证书')

    # 恢复入口必须从设备本机明确确认，不信任下载文件中的确认标记。
    enrollment['independent_recovery_verified'] = recovery_verified
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    root_owned_path(ROOT, directory=True)
    manager = SshManagement(device_id, load_enrollment=False)
    with manager.lock():
        if any(os.path.lexists(path) for path in (manager.settings_path, manager.state_path, SERVER_CA)):
            raise SshManagementError('已有纳管配置或策略，请按凭据轮换流程处理')
        atomic_write(SERVER_CA, ca_data)
        try:
            atomic_write(manager.settings_path, json.dumps(enrollment))
            manager = SshManagement(device_id)
            manager.verify_account()
            # 空状态在认证后、领取任务前被拒绝，可核对凭据且不会执行任务。
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    manager.base_url + '/poll/', json={}, verify=manager.verify,
                    headers={'Authorization': 'Bearer ' + manager.credential},
                    timeout=(3, 5), allow_redirects=False,
                )
            body = response.json()
            if (response.status_code != 400 or not isinstance(body, dict)
                    or not {'account', 'mode', 'keys'}.issubset(body)):
                raise SshManagementError('平台未接受纳管凭据或 SSH Agent API 路径错误')
        except (OSError, ValueError, requests.RequestException):
            manager.settings_path.unlink(missing_ok=True)
            SERVER_CA.unlink(missing_ok=True)
            raise


def run_cli(args):
    """分发独立脚本和完整发布包共用的设备端子命令。"""
    if len(args) in (2, 3) and args[0] == 'enroll' and args[2:] in ([], ['--recovery-verified']):
        try:
            enroll(Path(args[1]), recovery_verified=len(args) == 3)
        except SshManagementError as exc:
            sys.exit(str(exc))
        except (OSError, ValueError, requests.RequestException):
            sys.exit('首次纳管失败，请核对纳管文件格式、平台证书和设备网络')
        print('首次纳管配置已就绪，重启 device-agent 后核对专用心跳')
    elif len(args) == 2 and args[0] == 'rollback':
        manager = SshManagement(args[1], load_enrollment=False)
        with manager.lock():
            state = manager.load_state()
            if state['mode'] == 'pending' and state['pending']['until'] <= time.time():
                manager.rollback(state)
    else:
        sys.exit('用法: ssh_management.py enroll <CA 文件> [--recovery-verified] < <纳管 JSON>')


if __name__ == '__main__':
    run_cli(sys.argv[1:])
