"""验证完整 Agent 的构建结果及本机安装事务。"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import agent_release as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / 'device-agent.pyz'
        release.build(self.bundle)
        self.old = self.root / 'agent.py'
        self.old.write_bytes(b'# previous working Agent\n')
        self.runtime = self.root / '.env'
        self.runtime.write_text('DEVICE_FIXTURE=untouched', encoding='ascii')
        self.backup = self.root / 'agent.py.previous'
        self.digest = hashlib.sha256(self.bundle.read_bytes()).hexdigest()

    def test_reproducible_archive_and_actual_cli_preflight(self):
        another = self.root / 'second.pyz'
        release.build(another)
        self.assertEqual(self.bundle.read_bytes(), another.read_bytes())
        with zipfile.ZipFile(another) as archive:
            self.assertEqual(set(archive.namelist()), set(release.PACKAGE_FILES))
        output = subprocess.check_output([sys.executable, '-I', str(another), '--check'], text=True)
        self.assertEqual(output.strip(), '1.7.4')

    def test_bundle_disables_the_legacy_updater_and_resolves_rollback_entry(self):
        code = """
import subprocess
import sys
import time
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import device_agent
import ssh_management
assert device_agent.BUNDLED_AGENT
with patch.object(device_agent, 'download_new_agent') as download:
    assert not device_agent.apply_agent_update()
    download.assert_not_called()
manager = object.__new__(ssh_management.SshManagement)
manager.device_id = 'DEV-release-test'
with patch.object(ssh_management, 'atomic_write') as write, patch.object(ssh_management, 'systemctl'):
    manager.arm_rollback(time.time() + 300)
    service = next(content for path, content, mode in [call.args for call in write.call_args_list]
                   if path.name == ssh_management.ROLLBACK_UNIT)
    assert f'ExecStart=/usr/bin/python3 {sys.argv[1]} rollback DEV-release-test' in service
"""
        # systemd unit validates a Linux-only path; use a temporary archive on Linux.
        if os.name != 'posix':
            self.skipTest('systemd rollback command requires Linux paths')
        subprocess.run([sys.executable, '-I', '-c', code, str(self.bundle)], check=True)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root Linux fixture')
    def test_installer_rejects_wrong_digest_without_touching_service(self):
        with patch.object(release, 'AGENT_PATH', self.old), patch.object(release, 'systemctl') as service:
            with self.assertRaisesRegex(ValueError, '摘要'):
                release.install(self.bundle, '0' * 64)
            self.assertEqual(self.old.read_bytes(), b'# previous working Agent\n')
            service.assert_not_called()
            self.assertFalse(self.backup.exists())

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root Linux fixture')
    def test_installer_uses_one_atomic_file_and_preserves_runtime_config(self):
        service_path = f'{{ argv[]={sys.executable} {self.old} ; }}'
        previous = self.old.read_bytes()
        with patch.multiple(release, AGENT_PATH=self.old, PYTHON=sys.executable), \
                patch.object(release, 'ensure_no_ssh_trial'), \
                patch.object(release, 'systemctl', return_value=service_path) as service, \
                patch.object(release, 'wait_stable_service'):
            release.install(self.bundle, self.digest)
            self.assertEqual(self.old.read_bytes(), self.bundle.read_bytes())
            self.assertEqual(self.backup.read_bytes(), previous)
            self.assertEqual(self.runtime.read_text(encoding='ascii'), 'DEVICE_FIXTURE=untouched')
            self.assertEqual([call.args[0] for call in service.call_args_list],
                             ['show', 'is-active', 'stop', 'reset-failed', 'start'])
            service.reset_mock()
            release.install(self.bundle, self.digest)
            self.assertEqual([call.args[0] for call in service.call_args_list], ['show', 'is-active'])
            self.assertEqual(self.backup.read_bytes(), previous)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root Linux fixture')
    def test_failed_start_restores_previous_file_and_service(self):
        previous = self.old.read_bytes()
        service_path = f'{{ argv[]={sys.executable} {self.old} ; }}'
        with patch.multiple(release, AGENT_PATH=self.old, PYTHON=sys.executable), \
                patch.object(release, 'ensure_no_ssh_trial'), \
                patch.object(release, 'systemctl', return_value=service_path) as service, \
                patch.object(release, 'wait_stable_service', side_effect=[RuntimeError('startup failed'), None]):
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                release.install(self.bundle, self.digest)
            self.assertEqual(self.old.read_bytes(), previous)
            self.assertEqual(service.call_args.args, ('restart', release.SERVICE))
            self.assertEqual(self.backup.read_bytes(), previous)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root Linux fixture')
    def test_new_ssh_trial_while_preflighting_does_not_replace_agent(self):
        saved = self.old.read_bytes()
        service_path = f'{{ argv[]={sys.executable} {self.old} ; }}'
        with patch.multiple(release, AGENT_PATH=self.old, PYTHON=sys.executable), \
                patch.object(release, 'ensure_no_ssh_trial', side_effect=[None, ValueError('SSH 正在试登')]), \
                patch.object(release, 'systemctl', return_value=service_path) as service, \
                patch.object(release, 'wait_stable_service'):
            with self.assertRaisesRegex(ValueError, 'SSH'):
                release.install(self.bundle, self.digest)
            self.assertEqual(service.call_args.args, ('restart', release.SERVICE))
            self.assertEqual(self.old.read_bytes(), saved)
            self.assertFalse(self.backup.exists())

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root Linux fixture')
    def test_pending_policy_is_checked_before_stopping_agent(self):
        import ssh_management

        state = self.root / 'state.json'
        state.write_text(json.dumps({'pending': {'fingerprint': 'test'}}))
        state.chmod(0o600)
        with patch.object(ssh_management, 'ROOT', self.root), \
                patch.object(release, 'AGENT_PATH', self.old), patch.object(release, 'systemctl') as service:
            with self.assertRaisesRegex(ValueError, 'SSH'):
                release.install(self.bundle, self.digest)
            service.assert_not_called()


if __name__ == '__main__':
    unittest.main()
