import base64
import hashlib
from datetime import timedelta

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

    def test_confirmation_requires_device_evidence(self):
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
