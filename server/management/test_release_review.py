"""Release checks for administrative auth, legacy Agents and package storage."""
import ast
import hashlib
import io
import os
import subprocess
import tempfile
from types import SimpleNamespace
import zipfile
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import CodePackage, DeploymentTask, Device, DeviceLogTask, DockerImage, Project, UpdateTask
from .serializers import DeploymentTaskSerializer


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReleaseReviewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='release-reviewer')
        cls.token = Token.objects.create(user=cls.user)
        cls.device = Device.objects.create(device_id='DEV-release-review', frp_enabled=False)
        cls.project = Project.objects.create(name='Review project', version='v1')
        cls.image = DockerImage.objects.create(
            name='review-image', tag='v1', full_name='example.invalid/review-image:v1',
            size=1, file_path='docker_images/review.tar',
        )
        cls.package = CodePackage.objects.create(
            name='Review package', version='v1', size=1, file_path='code_packages/review.zip',
        )
        cls.deployment = DeploymentTask.objects.create(device=cls.device, target_version='v1')
        cls.update = UpdateTask.objects.create(device=cls.device, from_version='v0', target_version='v1')

    def setUp(self):
        self.cleanup_patch = patch('management.system_logs.cleanup_logs')
        self.cleanup_patch.start()
        self.addCleanup(self.cleanup_patch.stop)

    def login(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_log_task_limit_claims_one_and_leaves_two_pending(self):
        for index in range(3):
            DeviceLogTask.objects.create(device=self.device, task_id=f'limit-{index}', task_type='list')
        response = self.client.get(f'/api/devices/{self.device.device_id}/pending_log_tasks/', {'limit': 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([task['task_id'] for task in response.data['tasks']], ['limit-0'])
        self.assertEqual(DeviceLogTask.objects.filter(device=self.device, status='processing').count(), 1)
        self.assertEqual(DeviceLogTask.objects.filter(device=self.device, status='pending').count(), 2)

    def test_invalid_log_task_limits_do_not_claim_tasks(self):
        for index in range(3):
            DeviceLogTask.objects.create(device=self.device, task_id=f'limit-{index}', task_type='list')
        for limit in ('0', '6', 'not-an-integer'):
            with self.subTest(limit=limit):
                response = self.client.get(f'/api/devices/{self.device.device_id}/pending_log_tasks/', {'limit': limit})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(DeviceLogTask.objects.filter(device=self.device, status='pending').count(), 3)
                self.assertFalse(DeviceLogTask.objects.filter(device=self.device, status='processing').exists())

    def test_anonymous_asset_crud_and_management_actions_are_denied(self):
        for route, obj in [('projects', self.project), ('images', self.image), ('code-packages', self.package)]:
            with self.subTest(route=route):
                collection = f'/api/{route}/'
                detail = f'{collection}{obj.pk}/'
                self.assertEqual(self.client.get(collection).status_code, 401)
                self.assertEqual(self.client.get(detail).status_code, 401)
                self.assertEqual(self.client.post(collection, {}, format='json').status_code, 401)
                self.assertEqual(self.client.patch(detail, {'name': 'unauthorized'}, format='json').status_code, 401)
                self.assertEqual(self.client.delete(detail).status_code, 401)
        for url in [
            f'/api/projects/{self.project.pk}/deploy_to_devices/',
            f'/api/projects/{self.project.pk}/set_config/',
            f'/api/images/{self.image.pk}/push_to_device/',
            '/api/images/upload/', '/api/code-packages/upload/',
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}, format='json').status_code, 401)

    def test_anonymous_task_writes_are_denied_but_legacy_reads_and_callbacks_work(self):
        for route, obj, terminal in [
            ('deployments', self.deployment, 'completed'), ('updates', self.update, 'success'),
        ]:
            with self.subTest(route=route):
                collection = f'/api/{route}/'
                detail = f'{collection}{obj.pk}/'
                self.assertEqual(self.client.post(collection, {}, format='json').status_code, 401)
                self.assertEqual(self.client.patch(detail, {'target_version': 'bad'}, format='json').status_code, 401)
                self.assertEqual(self.client.delete(detail).status_code, 401)
                response = self.client.get(collection, {'device': self.device.pk, 'status': 'pending'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([item['id'] for item in response.data['results']], [obj.pk])
                self.assertEqual(self.client.get(detail).status_code, 200)
                response = self.client.post(f'{detail}update_progress/',
                                            {'status': terminal, 'progress': 100}, format='json')
                self.assertEqual(response.status_code, 200)
                obj.refresh_from_db()
                self.assertEqual((obj.status, obj.progress), (terminal, 100))
        self.assertEqual(self.client.get(f'/api/devices/{self.device.device_id}/').status_code, 200)

    def test_authenticated_project_and_task_writes_remain_available(self):
        self.login()
        response = self.client.post('/api/projects/', {'name': 'Authorized project', 'version': 'v2'}, format='json')
        self.assertEqual(response.status_code, 201)
        for route, extra in [('deployments', {}), ('updates', {'from_version': 'v1'})]:
            with self.subTest(route=route):
                response = self.client.post(f'/api/{route}/',
                                            {'device': self.device.pk, 'target_version': 'v2', **extra}, format='json')
                self.assertEqual(response.status_code, 201, response.data)
                url = f'/api/{route}/{response.data["id"]}/'
                self.assertEqual(self.client.patch(url, {'target_version': 'v3'}, format='json').status_code, 200)
                self.assertEqual(self.client.delete(url).status_code, 204)

    def test_image_push_accepts_json_and_reports_missing_devices(self):
        self.login()
        payload = {'device_ids': [self.device.device_id, 'DEV-does-not-exist'],
                   'container_name': 'review-container', 'container_config': {'network_mode': 'host'}}
        response = self.client.post(f'/api/images/{self.image.pk}/push_to_device/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data['success'], response.data['failed']), (1, 1))
        task = DeploymentTask.objects.get(pk=response.data['created_tasks'][0]['task_id'])
        self.assertEqual(task.config['container_name'], payload['container_name'])
        self.assertEqual(task.config['container_config'], payload['container_config'])
        response = self.client.post(f'/api/images/{self.image.pk}/push_to_device/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_image_upload_still_accepts_multipart(self):
        self.login()
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with patch('management.views.load_docker_image', return_value=('uploaded', 'v2', 'synthetic-id')), \
                    patch('management.views.push_to_registry', return_value='example.invalid/uploaded:v2'):
                response = self.client.post('/api/images/upload/',
                                            {'file': SimpleUploadedFile('image.tar', b'synthetic-image')}, format='multipart')
            self.assertEqual(response.status_code, 201, response.data)
            image = DockerImage.objects.get(pk=response.data['id'])
            self.assertTrue(os.path.isfile(os.path.join(media_root, image.file_path)))

    def test_pushed_image_task_is_consumable_by_agent(self):
        self.login()
        container_config = {'ports': {'8088/tcp': 8088}, 'environment': {'MODE': 'review'}}
        response = self.client.post(f'/api/images/{self.image.pk}/push_to_device/',
                                    {'device_ids': [self.device.device_id], 'container_name': 'review-container',
                                     'container_config': container_config}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        task_id = response.data['created_tasks'][0]['task_id']
        self.client.credentials()
        response = self.client.get('/api/deployments/', {'device': self.device.pk, 'status': 'pending'})
        self.assertEqual(response.status_code, 200, response.data)
        task = next(item for item in response.data['results'] if item['id'] == task_id)
        self.assertEqual(task['image_info'],
                         {'name': self.image.name, 'tag': self.image.tag, 'full_name': self.image.full_name})
        self.assertEqual(task['container_name'], 'review-container')
        self.assertEqual(task['container_config'], container_config)
        self.assertEqual(task['config'], DeploymentTask.objects.get(pk=task_id).config)

        # Exercise the actual consumer without importing daemon logging or touching Docker.
        # Source checkout and deployment image intentionally have different app roots.
        agent_dir = settings.BASE_DIR / 'device-agent'
        if not agent_dir.is_dir():
            agent_dir = settings.BASE_DIR.parent / 'device-agent'
        source = (agent_dir / 'device-agent.py').read_text(encoding='utf-8-sig')
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'execute_deployment')
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout='Up synthetic-container', stderr=''))
        report = Mock()
        namespace = {
            'logger': Mock(), 'subprocess': SimpleNamespace(run=runner, TimeoutExpired=subprocess.TimeoutExpired),
            'time': SimpleNamespace(sleep=Mock()), 'save_version': Mock(), 'report_deployment_progress': report,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<deployment-agent-contract>', 'exec'), namespace)
        self.assertTrue(namespace['execute_deployment'](task))
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn(['docker', 'pull', self.image.full_name], commands)
        self.assertIn(['docker', 'run', '-d', '--name', 'review-container',
                       '-p', '8088:8088', '-e', 'MODE=review', '--restart', 'always', self.image.full_name], commands)
        namespace['save_version'].assert_called_once_with(self.image.tag)
        self.assertEqual(report.call_args.kwargs['status'], 'completed')

    def test_legacy_deployment_without_image_config_keeps_agent_defaults(self):
        response = self.client.get(f'/api/deployments/{self.deployment.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['image_info'], {})
        self.assertEqual(response.data['container_name'], 'middleware')
        self.assertEqual(response.data['container_config'], {})
        self.assertEqual(response.data['config'], {})

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_internal_registry_uses_request_host_without_mutating_stored_config(self):
        original = 'registry:5000/team/review-image:v1'
        self.deployment.config = {'image_name': 'team/review-image', 'image_tag': 'v1', 'full_name': original}
        self.deployment.save()
        for host, expected in [
            ('public.example.invalid:8081', 'public.example.invalid:5000/team/review-image:v1'),
            ('[2001:db8::5]:8081', '[2001:db8::5]:5000/team/review-image:v1'),
        ]:
            with self.subTest(host=host):
                response = self.client.get(f'/api/deployments/{self.deployment.pk}/', HTTP_HOST=host)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['image_info']['full_name'], expected)
                self.assertEqual(response.data['config']['full_name'], original)
                self.deployment.refresh_from_db()
                self.assertEqual(self.deployment.config['full_name'], original)
        self.assertEqual(DeploymentTaskSerializer(self.deployment).data['image_info']['full_name'], original)

    def test_public_registry_names_are_not_rewritten(self):
        for full_name in ('registry.example.invalid:5000/review:v1', 'localhost:5000/review:v1', 'review:v1'):
            with self.subTest(full_name=full_name):
                self.deployment.config = {'full_name': full_name}
                self.deployment.save()
                response = self.client.get(f'/api/deployments/{self.deployment.pk}/')
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['image_info']['full_name'], full_name)

    def test_package_upload_uses_unique_storage_names_and_keeps_legacy_download(self):
        self.login()
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('project/readme.txt', 'synthetic package')
        archive_bytes = content.getvalue()
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            # Display fields must never select a directory, including POSIX and Windows paths.
            metadata = [
                ('Normal package', 'v1'), ('../escape', 'v1'),
                ('/absolute/escape', 'v1'), ('C:\\escape', 'v1'),
                ('Package', '../../escape'), ('Package', 'C:\\escape'),
                ('Normal package', 'v1'),
            ]
            paths = []
            for name, version in metadata:
                with self.subTest(name=name, version=version):
                    response = self.client.post('/api/code-packages/upload/',
                                                {'file': SimpleUploadedFile('project.zip', archive_bytes),
                                                 'name': name, 'version': version}, format='multipart')
                    self.assertEqual(response.status_code, 201, response.data)
                    package = CodePackage.objects.get(pk=response.data['id'])
                    self.assertEqual((package.name, package.version), (name, version))
                    self.assertEqual(package.checksum, hashlib.md5(archive_bytes).hexdigest())
                    self.assertEqual(package.size, len(archive_bytes))
                    self.assertEqual(os.path.dirname(package.file_path), 'code_packages')
                    self.assertRegex(os.path.basename(package.file_path), r'^[0-9a-f]{32}\.zip$')
                    stored_path = os.path.join(media_root, package.file_path)
                    self.assertTrue(os.path.isfile(stored_path))
                    paths.append(package.file_path)
            self.assertEqual(len(paths), len(set(paths)))
            self.client.credentials()
            response = self.client.get(f'/api/code-packages/{package.pk}/download/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), archive_bytes)
            response.close()
            self.assertEqual(self.client.get('/api/code-packages/999999/download/').status_code, 404)

    def test_package_upload_keeps_tar_extensions_and_rejects_unsupported_files(self):
        self.login()
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for filename in ('project.tar.gz', 'project.tgz'):
                response = self.client.post('/api/code-packages/upload/',
                                            {'file': SimpleUploadedFile(filename, b'synthetic-archive')}, format='multipart')
                self.assertEqual(response.status_code, 201, response.data)
                self.assertRegex(os.path.basename(response.data['file_path']), r'^[0-9a-f]{32}\.tar\.gz$')
            self.assertEqual(self.client.post('/api/code-packages/upload/', {}, format='multipart').status_code, 400)
            response = self.client.post('/api/code-packages/upload/',
                                        {'file': SimpleUploadedFile('unsupported.txt', b'text')}, format='multipart')
            self.assertEqual(response.status_code, 400)
