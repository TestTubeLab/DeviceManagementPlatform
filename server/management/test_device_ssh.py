import base64
import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Device, DeviceSshManagement, DeviceSshTask, FrpServerConfig
from .views import build_frp_config_for_device


TOKEN = 'z' * 43
KEY = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0 ' + b'z' * 32).decode()
STATE = {
    'account': 'maintainer', 'mode': 'legacy', 'local_password': 'enabled', 'frp_target': 22,
    'independent_recovery_verified': True,
    'remote_publickey_only': False, 'host_fingerprints': [], 'keys': [],
    'pending_fingerprint': None, 'pending_until': None, 'login_observed': False, 'error': '',
}


@override_settings(DEVICE_SSH_MANAGEMENT_ENABLED=True)
class DeviceSshTests(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(device_id='DEV-ssh-tests', frp_enabled=True, frp_ssh_port=11258)
        self.other = Device.objects.create(device_id='DEV-ssh-other')
        DeviceSshManagement.objects.create(
            device=self.device, credential_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        )
        DeviceSshManagement.objects.create(
            device=self.other, credential_hash=hashlib.sha256(('b' * 43).encode()).hexdigest(),
        )
        self.staff = get_user_model().objects.create_user(username='staff', is_staff=True)
        self.admin = get_user_model().objects.create_user(username='ssh-admin', is_staff=True)
        self.admin.user_permissions.add(Permission.objects.get(codename='manage_device_ssh'))
        self.tasks = f'/api/devices/{self.device.device_id}/ssh-management/tasks/'

    def poll(self, state=None, device=None, secure=True):
        return self.client.post(
            f'/api/agent/ssh-management/{(device or self.device).device_id}/poll/',
            STATE if state is None else state, format='json', secure=secure,
            HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )

    def create(self, payload=None):
        return self.client.post(self.tasks, payload or {'operation': 'add_key', 'public_key': KEY},
                                format='json', secure=True)

    def report(self, task_id, device=None):
        return self.client.post(
            f'/api/agent/ssh-management/{(device or self.device).device_id}/receipt/',
            {'id': task_id, 'ok': True, 'error': ''}, format='json', secure=True,
            HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )

    def test_requires_specialized_permission_and_https(self):
        self.assertEqual(self.poll(secure=False).status_code, 403)
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.create().status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self.tasks, {}, format='json').status_code, 403)
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.poll().status_code, 200)
        self.assertEqual(self.create().status_code, 201)

    def test_agent_enrollment_preflight_authenticates_without_claiming_task(self):
        self.poll()
        self.client.force_authenticate(self.admin)
        created = self.create()
        self.assertEqual(created.status_code, 201)
        response = self.poll({})
        self.assertEqual(response.status_code, 400)
        self.assertTrue({'account', 'mode', 'keys'}.issubset(response.data))
        self.assertEqual(DeviceSshTask.objects.get(task_id=created.data['id']).status, 'pending')

    @override_settings(DEVICE_SSH_BUILTIN_TLS=True)
    def test_builtin_tls_does_not_allow_operator_credentials_on_legacy_http(self):
        login_url = '/api/auth/login/'
        payload = {'username': self.admin.username, 'password': 'isolated-fixture-password'}
        self.admin.set_password(payload['password'])
        self.admin.save(update_fields=['password'])
        self.assertEqual(self.client.post(login_url, payload, format='json').status_code, 403)
        login = self.client.post(login_url, payload, format='json', secure=True)
        self.assertEqual(login.status_code, 200)
        authorization = 'Token ' + login.data['token']
        self.assertEqual(self.client.get('/api/auth/user/', HTTP_AUTHORIZATION=authorization).status_code, 403)
        self.assertEqual(self.client.get('/api/auth/user/', HTTP_AUTHORIZATION=authorization, secure=True).status_code, 200)
        self.assertEqual(self.client.get('/api/platform/health/').status_code, 200)
        heartbeat = self.client.post(f'/api/devices/{self.device.device_id}/heartbeat/', {}, format='json')
        self.assertEqual(heartbeat.status_code, 200)

    def test_legacy_update_is_not_queued_or_delivered_after_ssh_enrollment(self):
        device_url = f'/api/devices/{self.device.device_id}/'
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(device_url + 'update_agent/').status_code, 409)
        self.device.config = {'pending_agent_update': True}
        self.device.save(update_fields=['config'])
        response = self.client.post(device_url + 'heartbeat/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['command'], 'update_agent')
        self.device.refresh_from_db()
        self.assertFalse(self.device.config['pending_agent_update'])

    def test_full_bundle_heartbeat_blocks_legacy_updates_without_enrollment(self):
        device = Device.objects.create(device_id='DEV-bundled', config={'pending_agent_update': True})
        url = f'/api/devices/{device.device_id}/'
        response = self.client.post(url + 'heartbeat/', {
            'agent_version': '1.7.4', 'agent_release_bundle': True,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['command'], 'update_agent')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(url + 'update_agent/').status_code, 409)
        device.refresh_from_db()
        self.assertTrue(device.config['agent_release_bundle'])
        self.assertFalse(device.config['pending_agent_update'])
        self.client.post(url + 'heartbeat/', {'agent_version': '1.7.3'}, format='json')
        self.assertEqual(self.client.post(url + 'update_agent/').status_code, 409)
        # 保留旧版设备的单文件更新行为。
        legacy = Device.objects.create(device_id='DEV-legacy')
        legacy_url = f'/api/devices/{legacy.device_id}/'
        self.assertEqual(self.client.post(legacy_url + 'update_agent/').status_code, 200)
        response = self.client.post(legacy_url + 'heartbeat/', {'agent_version': '1.7.3'}, format='json')
        self.assertEqual(response.data['command'], 'update_agent')

    @override_settings(DEVICE_SSH_MANAGEMENT_ENABLED=False)
    def test_released_entry_reports_disabled_without_opening_agent_or_writes(self):
        url = f'/api/devices/{self.device.device_id}/ssh-management/'
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['enabled'])
        self.assertEqual(response.data['state'], {})
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.poll().status_code, 403)

    @override_settings(DEVICE_SSH_PUBLIC_URL='https://platform.test:8443/api')
    def test_enrollment_issues_one_time_credential_only_to_authorized_operator(self):
        unconfigured = Device.objects.create(device_id='DEV-ssh-unconfigured')
        url = f'/api/devices/{unconfigured.device_id}/ssh-management/enrollment/'
        payload = {'account': 'jetson', 'independent_recovery_verified': False}
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.post(url, payload, format='json', secure=True).status_code, 403)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 403)
        response = self.client.post(url, payload, format='json', secure=True)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response.data['server_url'], 'https://platform.test:8443/api')
        self.assertEqual(len(response.data['credential']), 43)
        record = DeviceSshManagement.objects.get(device=unconfigured)
        self.assertEqual(record.credential_hash, hashlib.sha256(response.data['credential'].encode()).hexdigest())
        self.assertNotIn('credential', self.client.get(
            f'/api/devices/{unconfigured.device_id}/ssh-management/', secure=True,
        ).data)
        self.assertEqual(self.client.post(url, payload, format='json', secure=True).status_code, 409)

    def test_enrollment_requires_configured_https_url(self):
        unconfigured = Device.objects.create(device_id='DEV-ssh-unconfigured')
        url = f'/api/devices/{unconfigured.device_id}/ssh-management/enrollment/'
        self.client.force_authenticate(self.admin)
        with override_settings(DEVICE_SSH_PUBLIC_URL='http://platform.test/api'):
            response = self.client.post(
                url, {'account': 'jetson', 'independent_recovery_verified': False},
                format='json', secure=True,
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(DeviceSshManagement.objects.filter(device=unconfigured).exists())

    def test_agent_state_recovers_remote_policy_lock_without_confirm_receipt(self):
        fingerprint = 'SHA256:' + 'a' * 43
        active = {**STATE, 'mode': 'active', 'remote_publickey_only': True,
                  'frp_target': 2222, 'keys': [{'fingerprint': fingerprint, 'verified': True}]}
        self.assertEqual(self.poll({**active, 'keys': []}).status_code, 200)
        self.assertFalse(DeviceSshManagement.objects.get(device=self.device).frp_publickey_locked)
        self.assertEqual(self.poll(active).status_code, 200)
        self.assertFalse(DeviceSshManagement.objects.get(device=self.device).frp_publickey_locked)
        self.poll({**STATE, 'mode': 'pending', 'pending_fingerprint': fingerprint, 'login_observed': True})
        self.client.force_authenticate(self.admin)
        task = self.create({'operation': 'confirm', 'fingerprint': fingerprint, 'operator_verified': True})
        self.assertEqual(task.status_code, 201)
        self.assertEqual(self.poll().data['task']['id'], task.data['id'])
        DeviceSshTask.objects.filter(task_id=task.data['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.poll(active).status_code, 200)
        self.assertEqual(self.poll().status_code, 200)
        self.assertTrue(DeviceSshManagement.objects.get(device=self.device).frp_publickey_locked)

    def test_single_claim_receipt_and_device_isolation(self):
        self.assertEqual(self.poll(device=self.other).status_code, 403)
        self.poll()
        self.client.force_authenticate(self.admin)
        created = self.create()
        task_id = created.data['id']
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.report(task_id).status_code, 409)
        self.assertEqual(self.report(task_id, self.other).status_code, 403)
        self.assertEqual(self.poll().data['task']['id'], task_id)
        self.assertIsNone(self.poll().data['task'])
        self.assertEqual(self.report(task_id).status_code, 204)
        self.assertEqual(self.report(task_id).status_code, 204)
        task = DeviceSshTask.objects.get(task_id=task_id)
        self.assertEqual((task.status, task.payload, task.requested_by), ('completed', {}, self.admin))

    def test_expired_task_cannot_be_claimed(self):
        self.poll()
        self.client.force_authenticate(self.admin)
        task_id = self.create().data['id']
        DeviceSshTask.objects.filter(task_id=task_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(self.poll().data['task'])
        self.assertEqual(self.report(task_id).status_code, 409)
        self.assertEqual(DeviceSshTask.objects.get(task_id=task_id).status, 'expired')

    def test_invalid_public_key_and_extra_parameters_rejected(self):
        self.poll()
        self.client.force_authenticate(self.admin)
        for payload in (
            {'operation': 'add_key', 'public_key': '-----BEGIN OPENSSH PRIVATE KEY-----'},
            {'operation': 'add_key', 'public_key': 'command="fixed" ' + KEY},
            {'operation': 'add_key', 'public_key': KEY, 'account': 'root'},
            {'operation': 'activate', 'fingerprint': 'SHA256:' + 'a' * 43, 'operator_verified': False},
        ):
            self.assertEqual(self.create(payload).status_code, 400)
        self.assertFalse(DeviceSshTask.objects.exists())

    @patch('management.views.is_frp_firewall_policy_applied', return_value=True)
    def test_confirmation_requires_device_evidence(self, _mock_firewall_applied):
        self.device.frp_web_port = 11259
        self.device.save(update_fields=['frp_web_port'])
        fingerprint = 'SHA256:' + 'a' * 43
        self.poll({**STATE, 'mode': 'pending', 'pending_fingerprint': fingerprint})
        self.client.force_authenticate(self.admin)
        payload = {'operation': 'confirm', 'fingerprint': fingerprint, 'operator_verified': True}
        self.assertEqual(self.create(payload).status_code, 409)
        self.poll({**STATE, 'mode': 'pending', 'pending_fingerprint': fingerprint, 'login_observed': True})
        created = self.create(payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.poll().data['task']['payload']['external_port'], 11258)
        self.assertEqual(self.report(created.data['id']).status_code, 204)
        config = FrpServerConfig(
            server_addr='frp.test.invalid', server_port=7000, token='fixture',
            port_pool_start=11258, port_pool_end=11259,
        )
        self.assertEqual(build_frp_config_for_device(self.device, config)['tunnels']['ssh']['local_port'], 2222)

    def test_activation_requires_local_recovery_attestation(self):
        self.poll({**STATE, 'independent_recovery_verified': False})
        self.client.force_authenticate(self.admin)
        request = {'operation': 'activate', 'fingerprint': 'SHA256:' + 'a' * 43, 'operator_verified': True}
        self.assertEqual(self.create(request).status_code, 409)
        self.assertFalse(DeviceSshTask.objects.exists())
