"""验证 Agent 的 SSH 策略状态机，不调用当前机器的 systemd 或 SSH。"""

import base64
import hashlib
import io
import json
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ssh_management as ssh


def fixture_key(byte):
    wire = b'\0\0\0\x0bssh-ed25519\0\0\0 ' + byte * 32
    return (
        'SHA256:' + base64.b64encode(hashlib.sha256(wire).digest()).decode().rstrip('='),
        'ssh-ed25519 ' + base64.b64encode(wire).decode(),
    )


FRPC_SOURCE = """[common]
server_addr = test.invalid
[DEV-test_ssh]
type = tcp
local_ip = 127.0.0.1
local_port = 22
remote_port = 11258
[DEV-test_web]
local_ip = 127.0.0.1
local_port = 8088
remote_port = 11259
"""


class AgentSshTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.frpc = root / 'frpc.ini'
        self.frpc.write_text(FRPC_SOURCE, encoding='utf-8')
        fixtures = patch.multiple(
            ssh, ROOT=root, SERVER_CA=root / 'server-ca.crt', FRPC=self.frpc,
            DEVICE_ID_FILE=root / 'device-id',
            KEY_FILE=root / 'keys', root_owned_path=lambda *_a, **_kw: None,
            atomic_write=lambda path, data, *_args: (
                path.write_bytes(data) if isinstance(data, bytes) else path.write_text(data, encoding='utf-8')
            ),
        )
        fixtures.start()
        self.addCleanup(fixtures.stop)
        self.agent = ssh.SshManagement('DEV-test')
        self.agent.account = 'maintainer'
        self.agent.recovery_verified = True
        self.key_a = fixture_key(b'a')
        self.key_b = fixture_key(b'b')

    def test_enrollment_requires_https_and_uses_the_installed_private_ca(self):
        self.agent.settings_path.write_text(json.dumps({
            'account': 'maintainer', 'credential': 'x' * 43,
            'server_url': 'http://platform.example/api',
        }), encoding='utf-8')
        with self.assertRaisesRegex(ssh.SshManagementError, 'HTTPS'):
            ssh.SshManagement('DEV-test')

        self.agent.settings_path.write_text(json.dumps({
            'account': 'maintainer', 'credential': 'x' * 43,
            'server_url': 'https://platform.example:8443/api',
            'independent_recovery_verified': True,
        }), encoding='utf-8')
        ssh.SERVER_CA.write_text('trusted private CA fixture', encoding='ascii')
        enrolled = ssh.SshManagement('DEV-test')
        self.assertEqual(enrolled.base_url, 'https://platform.example:8443/api/agent/ssh-management/DEV-test')
        self.assertEqual(enrolled.verify, str(ssh.SERVER_CA))
        self.assertTrue(enrolled.recovery_verified)

        enrollment = json.loads(self.agent.settings_path.read_text(encoding='utf-8'))
        enrollment['account'] = 'root'
        self.agent.settings_path.write_text(json.dumps(enrollment), encoding='utf-8')
        with self.assertRaisesRegex(ssh.SshManagementError, '禁止使用 root'):
            ssh.SshManagement('DEV-test')

    def test_key_validation_and_fingerprint(self):
        self.assertEqual(ssh.public_key(self.key_a[1]), self.key_a)
        for invalid in ('command="date" ' + self.key_a[1], self.key_a[1] + '\n' + self.key_b[1], None):
            with self.assertRaises(ssh.SshManagementError):
                ssh.public_key(invalid)

    def test_enrollment_checks_device_and_tls_and_leaves_recovery_unconfirmed(self):
        ssh.DEVICE_ID_FILE.write_text('DEV-test\n', encoding='ascii')
        ca = ssh.ROOT / 'ca-input'
        ca.write_bytes(b'-----BEGIN CERTIFICATE-----\nfixture')
        enrollment = {
            'device_id': 'DEV-other', 'account': 'maintainer', 'credential': 'x' * 43,
            'server_url': 'https://platform.example:8443/api', 'independent_recovery_verified': True,
        }
        with (
            patch.object(ssh.os, 'geteuid', return_value=0, create=True),
            patch.object(ssh.SshManagement, 'verify_account'),
            patch.object(ssh.SshManagement, 'lock', side_effect=nullcontext),
            patch.object(ssh.requests, 'Session') as session,
        ):
            with patch.object(ssh.sys, 'stdin', io.StringIO(json.dumps(enrollment))):
                with self.assertRaisesRegex(ssh.SshManagementError, '设备 ID'):
                    ssh.enroll(ca)
            session.assert_not_called()
            enrollment['device_id'] = 'DEV-test'
            post = session.return_value.__enter__.return_value.post
            post.side_effect = ssh.requests.exceptions.SSLError
            with patch.object(ssh.sys, 'stdin', io.StringIO(json.dumps(enrollment))):
                with self.assertRaises(ssh.requests.exceptions.SSLError):
                    ssh.enroll(ca)
            self.assertFalse(ssh.SERVER_CA.exists())
            self.assertFalse(self.agent.settings_path.exists())
            post.side_effect = None
            post.return_value = SimpleNamespace(status_code=403, json=lambda: {'detail': '设备认证失败'})
            with patch.object(ssh.sys, 'stdin', io.StringIO(json.dumps(enrollment))):
                with self.assertRaisesRegex(ssh.SshManagementError, '未接受纳管凭据'):
                    ssh.enroll(ca)
            self.assertFalse(self.agent.settings_path.exists())
            post.return_value = SimpleNamespace(
                status_code=400, json=lambda: {key: ['required'] for key in ('account', 'mode', 'keys')},
            )
            with patch.object(ssh.sys, 'stdin', io.StringIO(json.dumps(enrollment))):
                ssh.enroll(ca)
            self.assertFalse(ssh.SshManagement('DEV-test').recovery_verified)
            self.assertEqual(post.call_args.kwargs['verify'], str(ssh.SERVER_CA))
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            with patch.object(ssh.sys, 'stdin', io.StringIO(json.dumps(enrollment))):
                with self.assertRaisesRegex(ssh.SshManagementError, '已有'):
                    ssh.enroll(ca)

    def test_local_frp_guard_survives_missing_enrollment_dependencies(self):
        self.agent.settings_path.write_text('broken', encoding='utf-8')
        self.agent.save_state({'mode': 'active', 'verified': [self.key_a[0]]})
        with self.assertRaises(ValueError):
            ssh.SshManagement('DEV-test')
        offline = ssh.SshManagement('DEV-test', load_enrollment=False)
        self.assertIn('local_port = 2222', offline.render_cloud_config(FRPC_SOURCE))

    def test_poll_writes_managed_public_key_and_reports_success(self):
        self.agent.base_url = 'https://platform.example/api/agent/ssh-management/DEV-test'
        self.agent.credential = 'x' * 43
        task = {
            'id': 'a' * 32, 'operation': 'add_key',
            'expires_at': ssh.datetime.fromtimestamp(time.time() + 100, ssh.timezone.utc).isoformat(),
            'payload': {'fingerprint': self.key_a[0], 'public_key': self.key_a[1]},
        }
        with (
            patch.object(self.agent, 'lock', side_effect=nullcontext),
            patch.object(self.agent, 'verify_account'),
            patch.object(self.agent, 'status', return_value={'mode': 'legacy'}),
            patch.object(ssh.requests, 'Session') as session,
        ):
            post = session.return_value.__enter__.return_value.post
            post.side_effect = [
                SimpleNamespace(status_code=200, json=lambda: {'task': task}),
                SimpleNamespace(status_code=204),
                SimpleNamespace(status_code=200, json=lambda: {'task': None}),
            ]
            self.agent.poll()
            self.assertEqual(self.agent.managed_keys(), dict([self.key_a]))
            self.assertEqual(self.agent.config()['DEV-test_ssh']['local_port'], '22')
            self.agent.poll()
            receipt_call = post.call_args_list[1]
            self.assertTrue(receipt_call.args[0].endswith('/receipt/'))
            self.assertEqual(receipt_call.kwargs['json'], {'id': task['id'], 'ok': True, 'error': ''})
            self.assertFalse((ssh.ROOT / 'receipt.json').exists())

    def test_cannot_switch_if_another_alias_exposes_22_or_port_changed(self):
        self.agent.store_keys(dict([self.key_a]))
        with self.assertRaisesRegex(ssh.SshManagementError, '外部端口'):
            self.agent.execute('activate', {'fingerprint': self.key_a[0], 'external_port': 11260})
        self.frpc.write_text(FRPC_SOURCE + '[other]\nlocal_port=022\n', encoding='utf-8')
        with self.assertRaisesRegex(ssh.SshManagementError, '其它 SSH'):
            self.agent.execute('activate', {'fingerprint': self.key_a[0], 'external_port': 11258})

    def test_switch_preserves_web_and_rollback_does_not_reenable_disabled_frp(self):
        self.agent.store_keys(dict([self.key_a]))
        calls = []

        def systemctl(*args):
            calls.append(args)
            if args[0] == 'show':
                return SimpleNamespace(stdout=f'/usr/local/bin/frpc -c {self.frpc} ;')
            return SimpleNamespace(stdout='')

        with (
            patch.object(ssh, 'systemctl', side_effect=systemctl),
            patch.object(self.agent, 'start_sshd'),
            patch.object(self.agent, 'frpc_running', return_value=True),
            patch.object(self.agent, 'arm_rollback') as arm,
        ):
            self.agent.execute('activate', {'fingerprint': self.key_a[0], 'external_port': 11258})
            arm.assert_called_once()
            self.assertEqual(self.agent.config()['DEV-test_ssh']['local_port'], '2222')
            self.assertEqual(self.agent.config()['DEV-test_web']['remote_port'], '11259')
            self.agent.note_frp_enabled(False)
            self.agent.rollback(self.agent.load_state())
        self.assertEqual(self.agent.load_state()['mode'], 'rolled_back')
        self.assertEqual(self.agent.config()['DEV-test_ssh']['local_port'], '22')
        self.assertEqual(self.agent.config()['DEV-test_web']['local_port'], '8088')
        self.assertEqual(calls.count(('restart', ssh.FRPC_UNIT)), 1)

    def test_active_guard_survives_restart_and_failed_source_updates(self):
        self.agent.save_state({'mode': 'active', 'verified': [self.key_a[0]]})
        restored = ssh.SshManagement('DEV-test')
        applied = restored.render_cloud_config(FRPC_SOURCE)
        self.assertIn('local_port = 2222', applied)
        self.assertIn('local_port = 8088', applied)
        with self.assertRaises(ssh.SshManagementError):
            restored.render_cloud_config(FRPC_SOURCE.replace('DEV-test_ssh', 'unknown_ssh'))
        restored.rollback(restored.load_state())
        self.assertEqual(restored.load_state()['mode'], 'active')

    def test_rotation_requires_independent_key_evidence(self):
        a, b = self.key_a[0], self.key_b[0]
        self.agent.store_keys(dict([self.key_a, self.key_b]))
        self.agent.save_state({'mode': 'active', 'verified': [a]})
        self.frpc.write_text(self.agent.render_cloud_config(FRPC_SOURCE), encoding='utf-8')
        with self.assertRaisesRegex(ssh.SshManagementError, '已实测'):
            self.agent.execute('remove_key', {'fingerprint': a})
        with (
            patch.object(self.agent, 'sshd_ready'),
            patch.object(self.agent, 'frpc_running', return_value=True),
            patch.object(self.agent, 'login_observed', return_value=False) as observed,
        ):
            payload = {'fingerprint': b, 'external_port': 11258}
            self.agent.execute('verify_key', payload)
            with self.assertRaisesRegex(ssh.SshManagementError, '未观察到'):
                self.agent.execute('confirm', payload)
            observed.return_value = True
            self.agent.execute('confirm', payload)
            self.agent.execute('remove_key', {'fingerprint': a})
        self.assertEqual(list(self.agent.managed_keys()), [b])
        self.assertEqual(self.agent.load_state()['verified'], [b])

    def test_login_evidence_is_scoped_to_exact_account_unit_key_and_time(self):
        fp = self.key_a[0]
        now = time.time()
        record = {
            '_UID': '0', '_SYSTEMD_UNIT': ssh.SSHD_UNIT, '__REALTIME_TIMESTAMP': str(int(now * 1_000_000) + 5),
            'MESSAGE': f'Accepted publickey for maintainer from 127.0.0.1 port 42111 ssh2: ED25519 {fp}',
        }
        invalid_records = [
            {**record, '_UID': '1000'}, {**record, '_SYSTEMD_UNIT': 'ssh.service'},
            {**record, '__REALTIME_TIMESTAMP': '1'},
            {**record, 'MESSAGE': record['MESSAGE'].replace('127.0.0.1', '192.0.2.5')},
        ]
        with patch.object(ssh, 'run') as command:
            command.return_value.stdout = '\n'.join(map(json.dumps, invalid_records))
            self.assertFalse(self.agent.login_observed(now, fp))
            command.return_value.stdout += '\n' + json.dumps(record)
            self.assertTrue(self.agent.login_observed(now, fp))


if __name__ == '__main__':
    unittest.main()
