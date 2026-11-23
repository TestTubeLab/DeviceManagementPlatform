"""构建完整 Agent 发布包，并在可信设备端安装经过核验的包。"""

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

AGENT_PATH = Path('/opt/device-agent/agent.py')
SERVICE = 'device-agent.service'
PYTHON = '/usr/bin/python3'
MAX_BUNDLE_BYTES = 1024 * 1024
PACKAGE_FILES = {
    'device_agent.py': 'device-agent.py',
    'ssh_management.py': 'ssh_management.py',
    'agent_release.py': 'agent_release.py',
    '__main__.py': 'release_main.py',
}


def build(output):
    """构建内容包含完整 Agent 和安装入口的可复现 Python zipapp。"""
    source = Path(__file__).parent
    with zipfile.ZipFile(output, 'w') as archive:
        for target, filename in PACKAGE_FILES.items():
            data = (source / filename).read_bytes().replace(b'\r\n', b'\n')
            compile(data, target, 'exec')
            archive.writestr(zipfile.ZipInfo(target), data)


def systemctl(*args):
    return subprocess.run(
        ['/usr/bin/systemctl', *args], capture_output=True, text=True, check=True, timeout=30,
    ).stdout


def wait_stable_service():
    """等待同一次 systemd 启动稳定存活，识别快速退出和反复重启。"""
    deadline = time.monotonic() + 20
    stable_pid = ''
    stable_since = 0
    while time.monotonic() < deadline:
        lines = systemctl('show', '-p', 'ActiveState,MainPID', SERVICE).splitlines()
        props = dict(line.split('=', 1) for line in lines if '=' in line)
        pid = props.get('MainPID', '')
        if props.get('ActiveState') == 'active' and pid.isdecimal() and pid != '0':
            now = time.monotonic()
            if pid != stable_pid:
                stable_pid, stable_since = pid, now
            if now - stable_since >= 6:
                return
        else:
            stable_pid = ''
        time.sleep(0.5)
    raise RuntimeError('Agent 未能持续运行，请检查 device-agent.service 日志')


def ensure_no_ssh_trial():
    """试登期间保留当前 Agent 和定时回退入口。"""
    from ssh_management import ROOT, root_owned_path

    path = ROOT / 'state.json'
    if os.path.lexists(path):
        root_owned_path(path)
        if json.loads(path.read_text(encoding='utf-8')).get('pending'):
            raise ValueError('SSH 正在试登，确认或自动回退后再升级')


def install(bundle, expected_digest):
    """安装已在执行前核验的发布包，并在替换前再次核对摘要。"""
    from fcntl import LOCK_EX, LOCK_NB, flock

    if os.geteuid() != 0:
        raise PermissionError('请在目标设备的可信 root 终端运行安装')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_digest):
        raise ValueError('请输入发行记录中的完整 SHA-256 摘要')
    with bundle.open('rb') as source:
        data = source.read(MAX_BUNDLE_BYTES + 1)
    if len(data) > MAX_BUNDLE_BYTES or hashlib.sha256(data).hexdigest() != expected_digest.lower():
        raise ValueError('Agent 发布包大小或摘要不符')
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if sorted(archive.namelist()) != sorted(PACKAGE_FILES) or archive.testzip() is not None:
            raise ValueError('Agent 发布包内容不完整')

    directory = AGENT_PATH.parent
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError('Agent 目录必须由 root 所有且仅允许 root 写入')
    # 锁文件固定保留，避免两个安装器分别锁住不同 inode。
    fd = os.open(directory / '.release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        flock(lock, LOCK_EX | LOCK_NB)
        info = AGENT_PATH.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('现有 Agent 文件归属或权限异常')
        ensure_no_ssh_trial()
        argv = systemctl('show', '-p', 'ExecStart', '--value', SERVICE)
        if not re.search(r'argv\[\]=' + re.escape(f'{PYTHON} {AGENT_PATH}') + r'\s+;', argv):
            raise ValueError('现有 Agent 服务未使用标准 Python 启动路径')
        systemctl('is-active', '--quiet', SERVICE)
        if AGENT_PATH.read_bytes() == data:
            wait_stable_service()
            return '此发行包已安装，Agent 正常运行'
        with tempfile.TemporaryDirectory(prefix='.release-', dir=directory) as temporary:
            candidate = Path(temporary) / 'agent.py'
            with candidate.open('wb') as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            subprocess.run([PYTHON, '-I', str(candidate), '--check'], check=True, timeout=15)
            backup = AGENT_PATH.with_suffix('.py.previous')
            saved = Path(temporary) / 'previous'
            dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    systemctl('stop', SERVICE)
                    ensure_no_ssh_trial()
                    # 旧 Agent 可能在原地写入自更新文件，停稳后再做独立备份。
                    shutil.copy2(AGENT_PATH, saved)
                    with saved.open('rb') as stream:
                        os.fsync(stream.fileno())
                    os.replace(saved, backup)
                    os.fsync(dir_fd)
                    os.replace(candidate, AGENT_PATH)
                    os.fsync(dir_fd)
                    systemctl('reset-failed', SERVICE)
                    systemctl('start', SERVICE)
                    wait_stable_service()
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    try:
                        if not candidate.exists():
                            # 保留独立备份，恢复时仍使用原子替换。
                            shutil.copy2(backup, saved)
                            with saved.open('rb') as stream:
                                os.fsync(stream.fileno())
                            os.replace(saved, AGENT_PATH)
                            os.fsync(dir_fd)
                        systemctl('reset-failed', SERVICE)
                        systemctl('restart', SERVICE)
                        wait_stable_service()
                    except (OSError, RuntimeError, subprocess.SubprocessError) as recovery:
                        raise RuntimeError('Agent 安装及回退未成功，须从可信入口检查服务和备份') from recovery
                    raise
            finally:
                os.close(dir_fd)
    return '完整 Agent 已安装，服务启动验证通过'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('用法: python agent_release.py <输出 .pyz 路径>')
    build(Path(sys.argv[1]))
