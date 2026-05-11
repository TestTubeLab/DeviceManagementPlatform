from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Device, FrpServerConfig, Project, ProjectConfig, ProjectDeployment
from .views import build_device_id_from_fingerprint


class FrpManagementTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='tester', password='secret123')
        self.frp_config = FrpServerConfig.objects.create(
            server_addr='212.64.81.95',
            server_port=80,
            token='198631',
            port_pool_start=4430,
            port_pool_end=4435,
            is_active=True,
            config_version=1,
            description='test',
        )

    def test_fetch_frp_config_reads_database_and_allocates_port(self):
        device = Device.objects.create(
            device_id='DEV-fetch',
            name='Fetch Device',
            ip_address='10.0.0.10',
            frp_enabled=True,
        )

        response = self.client.get(f'/api/devices/{device.device_id}/fetch_frp_config/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['has_config'])
        self.assertEqual(response.data['server_addr'], '212.64.81.95')
        self.assertEqual(response.data['server_port'], 80)
        self.assertEqual(response.data['config_version'], 1)
        self.assertEqual(response.data['tunnels']['ssh']['remote_port'], 4430)

        device.refresh_from_db()
        self.assertEqual(device.frp_ssh_port, 4430)

    def test_fetch_frp_config_returns_disable_required_for_disabled_device(self):
        device = Device.objects.create(
            device_id='DEV-disabled',
            name='Disabled Device',
            ip_address='10.0.0.11',
            frp_enabled=False,
            frp_ssh_port=4430,
        )

        response = self.client.get(f'/api/devices/{device.device_id}/fetch_frp_config/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_config'])
        self.assertTrue(response.data['disable_required'])

    def test_set_frp_enabled_disable_releases_port_and_marks_agent_update(self):
        self.client.force_authenticate(user=self.user)
        device = Device.objects.create(
            device_id='DEV-toggle',
            name='Toggle Device',
            ip_address='10.0.0.12',
            frp_enabled=True,
            frp_ssh_port=4430,
            config={'agent_version': '1.6.0'},
        )

        response = self.client.post(
            f'/api/devices/{device.device_id}/set_frp_enabled/',
            {'enabled': False},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['frp_enabled'])

        device.refresh_from_db()
        self.assertFalse(device.frp_enabled)
        self.assertIsNone(device.frp_ssh_port)
        self.assertTrue(device.config.get('pending_agent_update'))

    @patch('management.views.sync_frps_service_config')
    def test_update_frp_config_reassigns_ports_and_bumps_version(self, mock_sync):
        self.client.force_authenticate(user=self.user)
        mock_sync.return_value = {
            'backup_path': '/root/frps-service/backups/frps-test.ini.bak',
            'service': {'status': 'running', 'running': True},
        }

        device_a = Device.objects.create(
            device_id='DEV-a',
            name='Device A',
            frp_enabled=True,
            frp_ssh_port=4430,
        )
        device_b = Device.objects.create(
            device_id='DEV-b',
            name='Device B',
            frp_enabled=True,
            frp_ssh_port=4431,
        )

        response = self.client.patch(
            '/api/frp/config/',
            {
                'port_pool_start': 4500,
                'port_pool_end': 4501,
                'server_addr': 'frp.example.com',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.frp_config.refresh_from_db()
        device_a.refresh_from_db()
        device_b.refresh_from_db()

        self.assertEqual(self.frp_config.config_version, 2)
        self.assertEqual(self.frp_config.server_addr, 'frp.example.com')
        self.assertEqual({device_a.frp_ssh_port, device_b.frp_ssh_port}, {4500, 4501})


class DeviceIdentityTests(APITestCase):
    def test_register_reuses_existing_device_by_hardware_fingerprint(self):
        device = Device.objects.create(
            device_id='DEV-existing',
            hardware_fingerprint='jetson_serial:serial-001',
            mac_address='00:11:22:33:44:55',
            ip_address='192.168.8.110',
            status='offline',
        )

        response = self.client.post(
            '/api/devices/register/',
            {
                'device_id': build_device_id_from_fingerprint('jetson_serial:serial-001'),
                'hardware_fingerprint': 'jetson_serial:serial-001',
                'mac_address': '00:11:22:33:44:55',
                'mac_addresses': ['00:11:22:33:44:55'],
                'ip_address': '192.168.31.36',
                'hostname': 'jetson-a',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['created'])
        self.assertEqual(response.data['device_id'], 'DEV-existing')
        self.assertEqual(Device.objects.count(), 1)

        device.refresh_from_db()
        self.assertEqual(device.ip_address, '192.168.31.36')
        self.assertEqual(device.hardware_fingerprint, 'jetson_serial:serial-001')

    def test_register_reuses_legacy_device_by_mac_and_backfills_fingerprint(self):
        device = Device.objects.create(
            device_id='DEV-legacy',
            mac_address='00:11:22:33:44:55',
            ip_address='192.168.8.110',
            status='offline',
        )

        response = self.client.post(
            '/api/devices/register/',
            {
                'device_id': build_device_id_from_fingerprint('jetson_serial:serial-002'),
                'hardware_fingerprint': 'jetson_serial:serial-002',
                'mac_address': '00:11:22:33:44:55',
                'mac_addresses': ['00:11:22:33:44:55', '00:11:22:33:44:66'],
                'ip_address': '192.168.31.40',
                'hostname': 'jetson-b',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['created'])
        self.assertEqual(response.data['device_id'], 'DEV-legacy')
        self.assertEqual(Device.objects.count(), 1)

        device.refresh_from_db()
        self.assertEqual(device.ip_address, '192.168.31.40')
        self.assertEqual(device.hardware_fingerprint, 'jetson_serial:serial-002')

    def test_register_ignores_stale_device_id_when_identity_does_not_match(self):
        Device.objects.create(
            device_id='DEV-stale',
            hardware_fingerprint='jetson_serial:serial-old',
            mac_address='00:11:22:33:44:55',
            ip_address='192.168.8.110',
        )

        response = self.client.post(
            '/api/devices/register/',
            {
                'device_id': 'DEV-stale',
                'hardware_fingerprint': 'jetson_serial:serial-new',
                'mac_address': '00:11:22:33:44:99',
                'mac_addresses': ['00:11:22:33:44:99'],
                'ip_address': '192.168.31.50',
                'hostname': 'jetson-c',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['created'])
        self.assertEqual(
            response.data['device_id'],
            build_device_id_from_fingerprint('jetson_serial:serial-new'),
        )
        self.assertEqual(Device.objects.count(), 2)

    def test_heartbeat_refreshes_ip_mac_and_hardware_fingerprint(self):
        device = Device.objects.create(
            device_id='DEV-heartbeat',
            ip_address='192.168.8.110',
            mac_address='00:11:22:33:44:55',
            status='offline',
        )

        response = self.client.post(
            f'/api/devices/{device.device_id}/heartbeat/',
            {
                'version': 'v1.7.1',
                'agent_version': '1.7.1',
                'hardware_fingerprint': 'jetson_serial:serial-heartbeat',
                'ip_address': '192.168.31.60',
                'mac_address': '00:11:22:33:44:77',
                'cpu_usage': 10,
                'memory_usage': 20,
                'disk_usage': 30,
                'container_status': 'running',
                'container_name': 'middleware',
                'container_uptime': '5m',
                'service_status': 'healthy',
                'service_response_time': 15,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        device.refresh_from_db()
        self.assertEqual(device.ip_address, '192.168.31.60')
        self.assertEqual(device.mac_address, '00:11:22:33:44:77')
        self.assertEqual(device.hardware_fingerprint, 'jetson_serial:serial-heartbeat')
        self.assertEqual(device.status, 'online')

    def test_install_script_preserves_existing_device_id(self):
        response = self.client.get('/api/install.sh')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('保留现有设备ID', content)
        self.assertNotIn('rm -f /etc/device-id', content)


class ProjectManagementTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='pm_tester', password='secret123')
        self.project = Project.objects.create(
            name='Project A',
            version='v1.0.0',
            local_image_name='newserver:latest',
            container_name='middleware',
        )
        self.device_a = Device.objects.create(device_id='DEV-project-a', ip_address='10.0.0.21')
        self.device_b = Device.objects.create(device_id='DEV-project-b', ip_address='10.0.0.22')

    def test_project_deployment_list_requires_auth_without_device_filter(self):
        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_a,
            deployed_version='v1.0.0',
            status='pending',
        )

        response = self.client.get('/api/project-deployments/')

        self.assertEqual(response.status_code, 401)

    def test_agent_project_deployment_list_only_returns_pending_tasks_for_own_device(self):
        ProjectConfig.objects.create(
            project=self.project,
            key='TOKEN',
            value='secret-value',
            is_secret=True,
        )
        pending = ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_a,
            deployed_version='v1.0.0',
            status='pending',
        )
        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_a,
            deployed_version='v0.9.0',
            status='completed',
        )
        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_b,
            deployed_version='v1.0.0',
            status='pending',
        )

        response = self.client.get(
            '/api/project-deployments/',
            {'device_id': self.device_a.device_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], pending.id)
        self.assertEqual(
            response.data['results'][0]['project_info']['configs'][0]['value'],
            'secret-value',
        )

    def test_set_project_config_removes_deleted_items(self):
        self.client.force_authenticate(user=self.user)
        ProjectConfig.objects.create(project=self.project, key='A', value='1')
        ProjectConfig.objects.create(project=self.project, key='B', value='2')

        response = self.client.post(
            f'/api/projects/{self.project.id}/set_config/',
            {
                'configs': [
                    {'key': 'A', 'value': 'updated', 'description': 'kept'},
                ]
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['deleted'], 1)
        self.assertEqual(ProjectConfig.objects.filter(project=self.project).count(), 1)
        self.assertTrue(ProjectConfig.objects.filter(project=self.project, key='A', value='updated').exists())
        self.assertFalse(ProjectConfig.objects.filter(project=self.project, key='B').exists())

    def test_project_detail_counts_distinct_non_failed_deployments(self):
        self.client.force_authenticate(user=self.user)
        self.device_b.auto_deploy_project = self.project
        self.device_b.save(update_fields=['auto_deploy_project'])

        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_a,
            deployed_version='v1.0.0',
            status='completed',
        )
        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_a,
            deployed_version='v1.0.1',
            status='pending',
        )
        ProjectDeployment.objects.create(
            project=self.project,
            device=self.device_b,
            deployed_version='v1.0.0',
            status='failed',
        )

        response = self.client.get(f'/api/projects/{self.project.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['deployed_devices_count'], 1)
