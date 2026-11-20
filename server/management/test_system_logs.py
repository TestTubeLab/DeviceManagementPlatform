"""Backend contracts for audit logs, remote log tasks and legacy task migration."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.parsers import JSONParser
from rest_framework.test import APITestCase

from . import system_logs
from .log_tasks import create_log_task
from .models import (
    DeploymentTask, Device, DeviceLog, DeviceLogTask, DockerImage, Project,
    ProjectDeployment, SystemLog, UpdateTask,
)


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    SECRET_KEY='synthetic-test-django-secret',
    FRP_CONFIG={'enabled': False, 'token': 'synthetic-test-frp-secret'},
)
class LogAPITestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'synthetic-test-password-42'
        cls.user = get_user_model().objects.create_user(
            username='log-reader', password=cls.password, is_staff=False,
        )
        cls.token = Token.objects.create(user=cls.user, key='a' * 40)
        cls.device = Device.objects.create(
            device_id='DEV-log-test', name='Synthetic device', status='online',
            last_heartbeat=timezone.now(), frp_enabled=False,
            config={'agent_version': '1.7.3', 'preserved': {'value': 42}},
        )

    def setUp(self):
        super().setUp()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        # Retention has separate clock-controlled tests; API tests must not share its flag.
        cleanup = patch('management.system_logs.cleanup_logs')
        cleanup.start()
        self.addCleanup(cleanup.stop)
        docker = patch('management.views.subprocess.run', side_effect=AssertionError('Unexpected external command'))
        docker.start()
        self.addCleanup(docker.stop)

    def device_url(self, action, device=None):
        return f'/api/devices/{(device or self.device).device_id}/{action}/'

    def create_event(self, **values):
        defaults = dict(
            level='INFO', module='project', action='create', actor=self.user.username,
            target='Synthetic project', result='success', message='ordinary event',
            device_id=self.device.device_id,
        )
        return SystemLog.objects.create(**{**defaults, **values})

    def assert_ids(self, response, expected):
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], len(expected))
        self.assertEqual([row['id'] for row in response.data['results']], expected)


class LogQueryTests(LogAPITestCase):
    def test_lists_and_details_require_login_and_allow_nonstaff(self):
        event = self.create_event()
        device_log = DeviceLog.objects.create(device=self.device, level='INFO', message='device event')
        urls = ['/api/system-logs/', f'/api/system-logs/{event.pk}/',
                '/api/logs/', f'/api/logs/{device_log.pk}/']
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.client.credentials()
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_system_logs_are_read_only_and_hide_internal_dedupe_key(self):
        event = self.create_event(event_key='synthetic-callback-key')
        response = self.client.get(f'/api/system-logs/{event.pk}/')
        self.assertNotIn('event_key', response.data)
        self.assertNotIn('event_key', self.client.get('/api/system-logs/').data['results'][0])
        for method, url in [('post', '/api/system-logs/'),
                            ('put', f'/api/system-logs/{event.pk}/'),
                            ('patch', f'/api/system-logs/{event.pk}/'),
                            ('delete', f'/api/system-logs/{event.pk}/')]:
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {'message': 'overwrite'}, format='json')
                self.assertEqual(response.status_code, 405)
        event.refresh_from_db()
        self.assertEqual(event.message, 'ordinary event')
        self.assertEqual(SystemLog.objects.count(), 1)

    def test_platform_filters_are_composable_with_inclusive_time_bounds(self):
        now = timezone.now()
        wanted = self.create_event(
            timestamp=now, level='ERROR', module='deployment', actor='Operator Alice',
            result='failed', message='needle deploy',
        )
        variants = [dict(timestamp=now - timedelta(seconds=1)), dict(timestamp=now + timedelta(seconds=1)),
                    dict(level='INFO'), dict(module='device'), dict(actor='Bob'),
                    dict(result='success'), dict(message='unrelated'), dict(device_id='DEV-other')]
        common = dict(timestamp=now, level='ERROR', module='deployment', actor='Operator Alice',
                      result='failed', message='needle deploy')
        for variant in variants:
            self.create_event(**{**common, **variant})
        params = dict(start_time=now.isoformat(), end_time=now.isoformat(), level='ERROR',
                      module='deployment', actor='alice', result='failed', search='NEEDLE',
                      device_id=self.device.device_id)
        self.assert_ids(self.client.get('/api/system-logs/', params), [wanted.pk])

    def test_platform_searches_message_target_action_but_not_detail(self):
        events = [self.create_event(**{field: 'unique-marker'})
                  for field in ('message', 'target', 'action', 'detail')]
        self.assert_ids(self.client.get('/api/system-logs/', {'search': 'unique-marker'}),
                        [event.pk for event in reversed(events[:3])])

    def test_device_log_filters_use_public_device_id_and_time_level_search(self):
        now = timezone.now()
        wanted = DeviceLog.objects.create(device=self.device, timestamp=now, level='ERROR', message='needle')
        other = Device.objects.create(device_id='DEV-other')
        for values in [dict(device=other), dict(level='INFO'), dict(message='unrelated'),
                       dict(timestamp=now - timedelta(seconds=1)), dict(timestamp=now + timedelta(seconds=1))]:
            defaults = dict(device=self.device, timestamp=now, level='ERROR', message='needle')
            DeviceLog.objects.create(**{**defaults, **values})
        params = dict(device_id=self.device.device_id, level='ERROR', search='NEEDLE',
                      start_time=now.isoformat(), end_time=now.isoformat())
        self.assert_ids(self.client.get('/api/logs/', params), [wanted.pk])

    def test_both_lists_paginate_stably_and_cap_page_size(self):
        now = timezone.now()
        for model, url, common in [(SystemLog, '/api/system-logs/', dict(module='system', result='success')),
                                    (DeviceLog, '/api/logs/', dict(device=self.device))]:
            with self.subTest(url=url):
                rows = model.objects.bulk_create([
                    model(timestamp=now, level='INFO', message=str(index), **common) for index in range(105)
                ])
                expected = sorted([row.pk for row in rows], reverse=True)
                first = self.client.get(url)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.data['count'], 105)
                self.assertEqual([row['id'] for row in first.data['results']], expected[:50])
                self.assertIsNone(first.data['previous'])
                self.assertIsNotNone(first.data['next'])
                second = self.client.get(url, {'page_size': 1000, 'page': 2})
                self.assertEqual(second.status_code, 200)
                self.assertEqual([row['id'] for row in second.data['results']], expected[100:])
                self.assertIsNone(second.data['next'])
                self.assertIsNotNone(second.data['previous'])
                capped = self.client.get(url, {'page_size': 1000})
                self.assertEqual(len(capped.data['results']), 100)
                for invalid_size in (0, -1, 'invalid'):
                    fallback = self.client.get(url, {'page_size': invalid_size})
                    self.assertEqual(fallback.status_code, 200)
                    self.assertEqual(len(fallback.data['results']), 50)
                for page in (0, -1, 999, 'invalid'):
                    self.assertEqual(self.client.get(url, {'page': page}).status_code, 404)

    def test_invalid_filters_and_reversed_ranges_are_rejected(self):
        invalid = [dict(level='TRACE'), dict(result='unknown'), dict(start_time='not-a-date'),
                   dict(end_time='not-a-date'), dict(device_id='x' * 101), dict(search='x' * 201),
                   dict(start_time='2026-11-18T02:00:00Z', end_time='2026-11-18T01:00:00Z')]
        for url in ('/api/system-logs/', '/api/logs/'):
            for params in invalid:
                with self.subTest(url=url, params=params):
                    self.assertEqual(self.client.get(url, params).status_code, 400)


class OperationAuditTests(LogAPITestCase):
    def test_successful_and_failed_login_record_outcomes_without_credentials(self):
        self.client.credentials()
        payload = dict(username=self.user.username, password=self.password,
                       nested={'api_key': 'synthetic-nested-key'},
                       unrelated='synthetic-body-not-for-audit')
        good = self.client.post('/api/auth/login/', payload, format='json')
        self.assertEqual(good.status_code, 200)
        payload['password'] = 'synthetic-wrong-password'
        bad = self.client.post('/api/auth/login/', payload, format='json')
        self.assertEqual(bad.status_code, 401)
        logs = list(SystemLog.objects.filter(module='auth', action='user_login').order_by('id'))
        self.assertEqual([row.result for row in logs], ['success', 'failed'])
        self.assertEqual([row.actor for row in logs], [self.user.username] * 2)
        self.assertEqual([row.level for row in logs], ['INFO', 'ERROR'])
        stored = json.dumps(list(SystemLog.objects.values()), default=str)
        for secret in (self.password, payload['password'], 'synthetic-nested-key',
                       payload['unrelated'], good.data['token']):
            self.assertNotIn(secret, stored)

    def test_project_crud_and_deletion_keep_actor_and_target_snapshot(self):
        created = self.client.post('/api/projects/', {'name': 'Audit project', 'version': 'v1'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        project_id = created.data['id']
        url = f'/api/projects/{project_id}/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(url, {'name': 'Renamed project', 'version': 'v2'}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(url, {'description': 'updated'}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(Project.objects.filter(pk=project_id).exists())
        logs = list(SystemLog.objects.filter(module='project').order_by('id'))
        self.assertEqual([row.action for row in logs], ['create', 'update', 'partial_update', 'destroy'])
        self.assertTrue(all(row.actor == self.user.username and row.result == 'success' for row in logs))
        self.assertIn('Renamed project', logs[-1].target)
        self.assertIn(str(project_id), logs[-1].target)
        self.assertTrue(all(row.event_key is None for row in logs))

    def test_anonymous_project_crud_retains_access_and_records_anonymous_actor(self):
        from rest_framework.permissions import AllowAny

        # Isolate instrumentation from the production administrative permission policy.
        with patch('management.views.ProjectViewSet.permission_classes', [AllowAny]):
            self.client.credentials()
            created = self.client.post('/api/projects/', {'name': 'Anonymous project', 'version': 'v1'}, format='json')
            self.assertEqual(created.status_code, 201)
            project_id = created.data['id']
            url = f'/api/projects/{project_id}/'
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.put(url, {'name': 'Anonymous renamed', 'version': 'v2'}, format='json').status_code, 200)
            self.assertEqual(self.client.patch(url, {'description': 'anonymous edit'}, format='json').status_code, 200)
            self.assertEqual(self.client.delete(url).status_code, 204)
            self.assertFalse(Project.objects.filter(pk=project_id).exists())
            events = list(SystemLog.objects.filter(module='project').order_by('id'))
            self.assertEqual([event.action for event in events], ['create', 'update', 'partial_update', 'destroy'])
            self.assertTrue(all(event.actor == 'anonymous' and event.result == 'success' for event in events))
            self.assertIn('Anonymous renamed', events[-1].target)

    def test_creating_pending_project_deployment_records_submission_with_task_id(self):
        project = Project.objects.create(name='Queued project', version='v1')
        response = self.client.post('/api/project-deployments/',
                                    {'project': project.pk, 'device': self.device.pk, 'deployed_version': 'v1', 'status': 'pending'},
                                    format='json')
        self.assertEqual(response.status_code, 201, response.data)
        task = ProjectDeployment.objects.get(pk=response.data['id'])
        self.assertEqual(task.status, 'pending')
        event = SystemLog.objects.get(module='deployment', action='create')
        self.assertEqual((event.result, event.task_id, event.device_id, event.actor),
                         ('submitted', str(task.pk), self.device.device_id, self.user.username))

    def test_all_rejected_image_push_records_failures_and_creates_no_deployment(self):
        image = DockerImage.objects.create(name='synthetic-image', tag='v1', full_name='synthetic-image:v1',
                                           size=1, file_path='docker_images/synthetic.tar')
        rejected_ids = ['DEV-missing-a', 'DEV-missing-b']
        # Isolate audit behavior from this existing route's form-only parser limitation.
        with patch('management.views.DockerImageViewSet.parser_classes', [JSONParser]):
            response = self.client.post(f'/api/images/{image.pk}/push_to_device/',
                                        {'device_ids': rejected_ids}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['success'], response.data['failed'], response.data['created_tasks']), (0, 2, []))
        self.assertFalse(DeploymentTask.objects.exists())
        self.assertEqual(SystemLog.objects.filter(action='push_to_device').count(), 2)
        self.assertCountEqual([item['device_id'] for item in response.data['failed_devices']], rejected_ids)
        for rejected in response.data['failed_devices']:
            event = SystemLog.objects.get(action='push_to_device', device_id=rejected['device_id'])
            self.assertEqual((event.result, event.level, event.task_id), ('failed', 'ERROR', ''))
            self.assertTrue(rejected['error'])
            self.assertIn(rejected['error'], event.detail)

    def test_batch_deploy_records_submitted_per_task_and_failure_per_rejected_device(self):
        project = Project.objects.create(name='Deploy project', version='v1')
        second = Device.objects.create(device_id='DEV-second')
        response = self.client.post(f'/api/projects/{project.pk}/deploy_to_devices/',
                                    {'device_ids': [self.device.device_id, second.device_id, 'DEV-missing']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['success'], response.data['failed']), (2, 1))
        tasks = ProjectDeployment.objects.filter(project=project)
        self.assertEqual(tasks.count(), 2)
        for task in tasks:
            event = SystemLog.objects.get(action='deploy_to_devices', task_id=str(task.pk))
            self.assertEqual((event.module, event.result, event.device_id),
                             ('deployment', 'submitted', task.device.device_id))
            self.assertEqual(task.status, 'pending')
        rejected = SystemLog.objects.get(action='deploy_to_devices', device_id='DEV-missing')
        self.assertEqual((rejected.result, rejected.level, rejected.task_id), ('failed', 'ERROR', ''))
        self.assertEqual(SystemLog.objects.filter(action='deploy_to_devices').count(), 3)

    def test_deploy_callbacks_record_terminal_success_failure_and_dedupe_repeats(self):
        project = Project.objects.create(name='Callback project', version='v1')
        self.client.credentials()
        for terminal, result, level in [('completed', 'success', 'INFO'), ('failed', 'failed', 'ERROR')]:
            with self.subTest(terminal=terminal):
                task = ProjectDeployment.objects.create(project=project, device=self.device, deployed_version='v1')
                url = f'/api/project-deployments/{task.pk}/update_progress/'
                response = self.client.post(url, {'status': 'pulling_code', 'progress': 20}, format='json')
                self.assertEqual(response.status_code, 200)
                self.assertFalse(SystemLog.objects.filter(task_id=str(task.pk), action='update_progress').exists())
                payload = dict(status=terminal, progress=100,
                               error_message='password=synthetic-callback-secret' if terminal == 'failed' else '')
                for _ in range(2):
                    self.assertEqual(self.client.post(url, payload, format='json').status_code, 200)
                event = SystemLog.objects.get(task_id=str(task.pk), action='update_progress')
                self.assertEqual((event.result, event.level, event.actor), (result, level, 'Agent'))
                self.assertEqual(event.device_id, self.device.device_id)
                self.assertTrue(event.event_key)
                self.assertNotIn('synthetic-callback-secret', event.detail)
                task.refresh_from_db()
                self.assertEqual(task.status, terminal)

    def test_same_primary_key_callbacks_from_three_task_types_have_distinct_audit_namespaces(self):
        project = Project.objects.create(name='Namespaced project', version='v1')
        tasks = [
            (DeploymentTask.objects.create(pk=1, device=self.device, target_version='v1'), 'deployments', 'completed'),
            (UpdateTask.objects.create(pk=1, device=self.device, from_version='v0', target_version='v1'), 'updates', 'success'),
            (ProjectDeployment.objects.create(pk=1, device=self.device, project=project, deployed_version='v1'),
             'project-deployments', 'completed'),
        ]
        self.client.credentials()
        for task, route, terminal in tasks:
            for _ in range(2):
                response = self.client.post(f'/api/{route}/{task.pk}/update_progress/',
                                            {'status': terminal, 'progress': 100}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
            task.refresh_from_db()
            self.assertEqual(task.status, terminal)
        events = list(SystemLog.objects.filter(action='update_progress', task_id='1'))
        self.assertEqual(len(events), 3)
        self.assertEqual(len({event.event_key for event in events}), 3)
        self.assertTrue(all(event.event_key and event.result == 'success' and event.actor == 'Agent'
                            and event.device_id == self.device.device_id for event in events))

    def test_heartbeat_polling_and_log_task_reports_do_not_create_audit_noise(self):
        task_id = create_log_task(self.device, 'list', {})
        self.client.credentials()
        with patch('management.middleware.OperationLogMiddleware.snapshot_target') as snapshot:
            for action in ('pending_log_tasks', 'pending_config', 'pending_system_tasks'):
                response = self.client.get(self.device_url(action))
                self.assertEqual(response.status_code, 200, response.data)
            response = self.client.post(self.device_url('heartbeat'), {'agent_version': '1.7.3'}, format='json')
            self.assertEqual(response.status_code, 200)
            response = self.client.post(self.device_url('report_log_task'),
                                        {'task_id': task_id, 'status': 'completed', 'result': {'files': []}}, format='json')
            self.assertEqual(response.status_code, 200)
            snapshot.assert_not_called()
        self.assertEqual(self.client.get(self.device_url('deployment')).status_code, 200)
        self.assertEqual(SystemLog.objects.count(), 0)

    def test_audit_database_failure_does_not_break_project_creation_or_transaction(self):
        self.create_event(event_key='synthetic-existing-event')
        create = SystemLog.objects.create

        def violate_unique_constraint(**event):
            # A real SQL failure marks the transaction broken unless the writer uses a savepoint.
            event['event_key'] = 'synthetic-existing-event'
            return create(**event)

        with patch('management.system_logs.SystemLog.objects.create', side_effect=violate_unique_constraint):
            with self.assertLogs('management.system_logs', level='ERROR'):
                response = self.client.post('/api/projects/', {'name': 'Survives audit failure', 'version': 'v1'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Project.objects.filter(pk=response.data['id']).exists())
        self.assertEqual(SystemLog.objects.count(), 1)
        self.assertEqual(self.client.patch(f"/api/projects/{response.data['id']}/", {'version': 'v2'}, format='json').status_code, 200)

    def test_cleanup_failure_does_not_break_successful_operation(self):
        with patch('management.system_logs.cleanup_logs', side_effect=RuntimeError('synthetic cleanup failure')):
            with self.assertLogs('management.system_logs', level='ERROR'):
                response = self.client.post('/api/projects/', {'name': 'Survives cleanup failure', 'version': 'v1'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SystemLog.objects.get().result, 'success')

    def test_audit_target_snapshot_failure_does_not_break_project_update(self):
        project = Project.objects.create(name='Snapshot failure project', version='v1')
        self.client.raise_request_exception = False
        with patch('management.middleware.Project.objects.filter', side_effect=RuntimeError('synthetic snapshot failure')):
            response = self.client.patch(f'/api/projects/{project.pk}/', {'version': 'v2'}, format='json')
        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.version, 'v2')

    def test_snapshot_helper_failure_preserves_crud_and_invalid_pk_responses(self):
        with patch('management.middleware.OperationLogMiddleware.snapshot_target',
                   side_effect=RuntimeError('synthetic snapshot helper failure')) as snapshot:
            with self.assertLogs('management.system_logs', level='ERROR'):
                created = self.client.post('/api/projects/', {'name': 'Snapshot wrapper project', 'version': 'v1'}, format='json')
                self.assertEqual(created.status_code, 201)
                project_id = created.data['id']
                self.assertEqual(Project.objects.get(pk=project_id).name, 'Snapshot wrapper project')
                url = f'/api/projects/{project_id}/'
                detail = self.client.get(url)
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.data['id'], project_id)
                updated = self.client.patch(url, {'version': 'v2'}, format='json')
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.data['version'], 'v2')
                self.assertEqual(Project.objects.get(pk=project_id).version, 'v2')
                self.assertEqual(self.client.delete(url).status_code, 204)
                self.assertFalse(Project.objects.filter(pk=project_id).exists())
                self.assertEqual(self.client.get('/api/projects/not-an-integer/').status_code, 404)
                self.assertEqual(self.client.patch('/api/projects/not-an-integer/', {'version': 'v3'}, format='json').status_code, 404)
        self.assertEqual(snapshot.call_count, 6)

    def test_response_audit_helper_failure_preserves_original_crud_responses(self):
        with patch('management.middleware.OperationLogMiddleware.record_response',
                   side_effect=RuntimeError('synthetic response audit helper failure')) as record_response:
            with self.assertLogs('management.system_logs', level='ERROR'):
                created = self.client.post('/api/projects/', {'name': 'Response wrapper project', 'version': 'v1'}, format='json')
                self.assertEqual(created.status_code, 201)
                project_id = created.data['id']
                self.assertEqual(Project.objects.get(pk=project_id).name, 'Response wrapper project')
                url = f'/api/projects/{project_id}/'
                detail = self.client.get(url)
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.data['id'], project_id)
                updated = self.client.patch(url, {'version': 'v2'}, format='json')
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.data['version'], 'v2')
                self.assertEqual(Project.objects.get(pk=project_id).version, 'v2')
                self.assertEqual(self.client.delete(url).status_code, 204)
                self.assertFalse(Project.objects.filter(pk=project_id).exists())
        self.assertEqual(record_response.call_count, 4)
        self.assertFalse(SystemLog.objects.exists())

    def test_uncaught_view_exception_logs_stack_without_secret_exception_values(self):
        self.client.raise_request_exception = False
        with patch('management.views.ProjectViewSet.list', side_effect=RuntimeError('synthetic-exception-credential')):
            response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, 500)
        event = SystemLog.objects.get()
        self.assertEqual((event.module, event.result, event.level), ('project', 'failed', 'ERROR'))
        self.assertIn('RuntimeError', event.message)
        self.assertTrue(event.detail)
        self.assertNotIn('synthetic-exception-credential', json.dumps(list(SystemLog.objects.values()), default=str))


class AuditRedactionTests(LogAPITestCase):
    def test_redacts_configured_inline_header_url_and_nested_request_credentials(self):
        payload = {'password': 'synthetic-request-password', 'nested': {'api_key': 'synthetic-api-key'},
                   'items': [{'private_key': 'synthetic-private-key'}, {'token': 'synthetic-request-token'}]}
        secrets = system_logs.request_secrets(payload)
        self.assertCountEqual(secrets, ['synthetic-request-password', 'synthetic-api-key',
                                        'synthetic-private-key', 'synthetic-request-token'])
        text = ' '.join(secrets + ['synthetic-test-django-secret', 'synthetic-test-frp-secret',
                                  'password=synthetic-inline-password', 'Bearer synthetic-bearer-token',
                                  'Token synthetic-header-token', 'https://tester:synthetic-url-password@example.invalid/'])
        system_logs.record_system_log(
            secrets=secrets, level='ERROR', module='system', action='test', result='failed', message=text, detail=text,
        )
        event = SystemLog.objects.get()
        for field in (event.message, event.detail):
            self.assertIn('[REDACTED]', field)
            for secret in secrets + ['synthetic-test-django-secret', 'synthetic-test-frp-secret',
                                      'synthetic-inline-password', 'synthetic-bearer-token',
                                      'synthetic-header-token', 'synthetic-url-password']:
                self.assertNotIn(secret, field)
        self.assertEqual(payload['password'], 'synthetic-request-password')

    def test_persisted_fields_are_bounded_after_redaction(self):
        limits = {'actor': 150, 'target': 300, 'message': 2000, 'detail': 16000, 'device_id': 100, 'task_id': 100}
        values = {key: 'password=synthetic-bound-secret ' + 'x' * (limit + 100) for key, limit in limits.items()}
        system_logs.record_system_log(level='INFO', module='system', action='test', result='success', **values)
        event = SystemLog.objects.get()
        for field, limit in limits.items():
            with self.subTest(field=field):
                self.assertEqual(len(getattr(event, field)), limit)
                self.assertNotIn('synthetic-bound-secret', getattr(event, field))

    def test_event_key_deduplicates_callback_but_null_keys_allow_independent_events(self):
        event = dict(level='INFO', module='deployment', action='update_progress', result='success', message='first')
        system_logs.record_system_log(event_key='synthetic-terminal-event', **event)
        system_logs.record_system_log(event_key='synthetic-terminal-event', **{**event, 'message': 'retry'})
        system_logs.record_system_log(**event)
        system_logs.record_system_log(**event)
        self.assertEqual(SystemLog.objects.count(), 3)
        self.assertEqual(SystemLog.objects.get(event_key='synthetic-terminal-event').message, 'first')
        self.assertEqual(SystemLog.objects.filter(event_key__isnull=True).count(), 2)


class RemoteLogTaskTests(LogAPITestCase):
    def test_seven_created_tasks_claim_five_then_remaining_two_without_double_claims(self):
        task_ids = []
        for index in range(7):
            response = self.client.post(self.device_url('list_logs'), {'date': f'2026-11-{index + 1:02d}'}, format='json')
            self.assertEqual(response.status_code, 200)
            task_ids.append(response.data['task_id'])
        self.assertEqual(len(set(task_ids)), 7)
        other = Device.objects.create(device_id='DEV-other')
        foreign_id = create_log_task(other, 'list', {})
        self.client.credentials()
        first = self.client.get(self.device_url('pending_log_tasks'))
        self.assertEqual(first.status_code, 200)
        self.assertEqual([task['task_id'] for task in first.data['tasks']], task_ids[:5])
        self.assertEqual(first.data['tasks'][0]['params'], {'date': '2026-11-01'})
        self.assertEqual(DeviceLogTask.objects.filter(device=self.device, status='processing').count(), 5)
        self.assertEqual(DeviceLogTask.objects.filter(device=self.device, status='pending').count(), 2)
        second = self.client.get(self.device_url('pending_log_tasks'))
        self.assertEqual([task['task_id'] for task in second.data['tasks']], task_ids[5:])
        self.assertEqual(self.client.get(self.device_url('pending_log_tasks')).data, {'tasks': []})
        self.assertEqual(DeviceLogTask.objects.get(device=other, task_id=foreign_id).status, 'pending')

    def test_terminal_results_are_immutable_even_for_conflicting_retries(self):
        for initial in ('completed', 'failed'):
            with self.subTest(initial=initial):
                task_id = create_log_task(self.device, 'read', {'date': '2026-11-18', 'file': 'synthetic.log'})
                self.client.get(self.device_url('pending_log_tasks'))
                payload = dict(task_id=task_id, status=initial, result={'content': 'original'}, error_message='original error')
                self.assertEqual(self.client.post(self.device_url('report_log_task'), payload, format='json').status_code, 200)
                task = DeviceLogTask.objects.get(task_id=task_id)
                completed_at = task.completed_at
                payload.update(status='failed' if initial == 'completed' else 'completed',
                               result={'content': 'replacement'}, error_message='replacement error')
                self.assertEqual(self.client.post(self.device_url('report_log_task'), payload, format='json').status_code, 200)
                task.refresh_from_db()
                self.assertEqual((task.status, task.result, task.error_message, task.completed_at),
                                 (initial, {'content': 'original'}, 'original error', completed_at))

    def test_expired_pending_and_processing_journal_tasks_are_not_executed_or_revived(self):
        now = timezone.now()
        for state in ('pending', 'processing'):
            task_id = create_log_task(self.device, 'journal', {'source': 'agent'})
            DeviceLogTask.objects.filter(task_id=task_id).update(status=state, created_at=now - timedelta(seconds=121))
        ids = list(DeviceLogTask.objects.values_list('task_id', flat=True))
        with patch('management.log_tasks.timezone.now', return_value=now):
            self.assertEqual(self.client.get(self.device_url('pending_log_tasks')).data, {'tasks': []})
            for task_id in ids:
                response = self.client.post(self.device_url('report_log_task'),
                                            {'task_id': task_id, 'status': 'completed', 'result': {'content': 'late'}}, format='json')
                self.assertEqual(response.status_code, 200)
                task = DeviceLogTask.objects.get(task_id=task_id)
                self.assertEqual(task.status, 'failed')
                self.assertEqual(task.result, {})
                self.assertTrue(task.error_message)
                self.assertEqual(task.completed_at, now)

    def test_result_lookup_expires_journal_before_any_poll(self):
        task_id = create_log_task(self.device, 'journal', {'source': 'system'})
        DeviceLogTask.objects.filter(task_id=task_id).update(created_at=timezone.now() - timedelta(seconds=121))
        response = self.client.get(self.device_url('log_task_result'), {'task_id': task_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'failed')
        self.assertTrue(response.data['completed_at'])

    def test_late_report_alone_cannot_revive_expired_journal(self):
        task_id = create_log_task(self.device, 'journal', {'source': 'agent'})
        DeviceLogTask.objects.filter(task_id=task_id).update(created_at=timezone.now() - timedelta(seconds=121))
        response = self.client.post(self.device_url('report_log_task'),
                                    {'task_id': task_id, 'status': 'completed', 'result': {'content': 'late'}}, format='json')
        self.assertEqual(response.status_code, 200)
        task = DeviceLogTask.objects.get(task_id=task_id)
        self.assertEqual((task.status, task.result), ('failed', {}))

    def test_nonjournal_tasks_do_not_expire_on_journal_deadline(self):
        task_id = create_log_task(self.device, 'read', {'date': '2026-11-18', 'file': 'synthetic.log'})
        DeviceLogTask.objects.filter(task_id=task_id).update(created_at=timezone.now() - timedelta(days=1))
        response = self.client.get(self.device_url('pending_log_tasks'))
        self.assertEqual([task['task_id'] for task in response.data['tasks']], [task_id])

    def test_journal_result_accepts_exactly_512_kib_of_content(self):
        task_id = create_log_task(self.device, 'journal', {'source': 'agent'})
        content = 'x' * (512 * 1024)
        response = self.client.post(self.device_url('report_log_task'),
                                    {'task_id': task_id, 'status': 'completed', 'result': {'content': content}}, format='json')
        self.assertEqual(response.status_code, 200)
        task = DeviceLogTask.objects.get(task_id=task_id)
        self.assertEqual((task.status, task.result['content']), ('completed', content))

    def test_journal_result_rejects_more_than_512_kib_measured_as_utf8_bytes(self):
        oversized = ['x' * (512 * 1024 + 1), '\u6d4b' * ((512 * 1024) // 3 + 1)]
        for content in oversized:
            with self.subTest(byte_size=len(content.encode('utf-8'))):
                task_id = create_log_task(self.device, 'journal', {'source': 'system'})
                self.client.get(self.device_url('pending_log_tasks'))
                response = self.client.post(self.device_url('report_log_task'),
                                            {'task_id': task_id, 'status': 'completed', 'result': {'content': content}}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                task = DeviceLogTask.objects.get(task_id=task_id)
                self.assertEqual((task.status, task.result, task.completed_at), ('processing', {}, None))

    def test_reports_reject_invalid_status_and_nonobject_results_without_mutating_task(self):
        task_id = create_log_task(self.device, 'read', {'date': '2026-11-18', 'file': 'synthetic.log'})
        invalid = [dict(status='pending', result={}), dict(status='processing', result={}),
                   dict(status='completed', result=[]), dict(status='completed', result=''),
                   dict(status='completed', result=None), dict(status='completed', result=['line'])]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(self.device_url('report_log_task'), {'task_id': task_id, **payload}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(DeviceLogTask.objects.get(task_id=task_id).status, 'pending')

    def test_results_and_reports_are_scoped_to_device_and_missing_ids_are_handled(self):
        other = Device.objects.create(device_id='DEV-other')
        task_id = create_log_task(other, 'read', {'date': '2026-11-18', 'file': 'synthetic.log'})
        self.assertEqual(self.client.get(self.device_url('log_task_result')).status_code, 400)
        self.assertEqual(self.client.get(self.device_url('log_task_result'), {'task_id': task_id}).status_code, 404)
        response = self.client.post(self.device_url('report_log_task'),
                                    {'task_id': task_id, 'status': 'completed', 'result': {}}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(DeviceLogTask.objects.get(task_id=task_id).status, 'pending')

    def test_service_logs_requires_login_and_rejects_offline_or_old_agents(self):
        url = self.device_url('service_logs')
        self.client.credentials()
        self.assertEqual(self.client.post(url, {'source': 'agent'}, format='json').status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        Device.objects.filter(pk=self.device.pk).update(last_heartbeat=timezone.now() - timedelta(seconds=121))
        self.assertEqual(self.client.post(url, {'source': 'agent'}, format='json').status_code, 409)
        for version in ('1.7.2', '1.6.0', 'unknown', ''):
            with self.subTest(version=version):
                Device.objects.filter(pk=self.device.pk).update(last_heartbeat=timezone.now(), config={'agent_version': version})
                self.assertEqual(self.client.post(url, {'source': 'agent'}, format='json').status_code, 409)
        self.assertEqual(DeviceLogTask.objects.count(), 0)

    def test_service_logs_validates_sources_ranges_line_and_keyword_bounds(self):
        invalid = [{}, {'source': 'shell'}, {'source': 'agent', 'lines': 0}, {'source': 'agent', 'lines': 2001},
                   {'source': 'agent', 'lines': -1}, {'source': 'agent', 'lines': 'bad'},
                   {'source': 'agent', 'level': 'TRACE'}, {'source': 'agent', 'keyword': 'x' * 201},
                   {'source': 'agent', 'start_time': 'bad'}, {'source': 'agent', 'end_time': 'bad'},
                   {'source': 'agent', 'start_time': '2026-11-18T02:00:00Z', 'end_time': '2026-11-18T01:00:00Z'}]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.device_url('service_logs'), payload, format='json').status_code, 400)
        self.assertEqual(DeviceLogTask.objects.count(), 0)

    def test_service_logs_accepts_all_new_sources_and_boundary_values(self):
        for index, source in enumerate(('agent', 'frpc', 'docker', 'system')):
            with self.subTest(source=source):
                payload = dict(source=source, lines=1 if index % 2 else 2000, level='ERROR', keyword='x' * 200,
                               start_time='2026-11-18T01:00:00Z', end_time='2026-11-18T01:00:00Z')
                response = self.client.post(self.device_url('service_logs'), payload, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                task = DeviceLogTask.objects.get(task_id=response.data['task_id'])
                self.assertEqual((task.task_type, task.status), ('journal', 'pending'))
                self.assertEqual((task.params['source'], task.params['lines'], task.params['keyword']),
                                 (source, payload['lines'], payload['keyword']))
                self.assertEqual(task.params['start_time'], task.params['end_time'])

    def test_service_log_defaults_use_last_hour_and_500_lines(self):
        now = timezone.now()
        with patch('management.log_tasks.timezone.now', return_value=now):
            response = self.client.post(self.device_url('service_logs'), {'source': 'agent'}, format='json')
        self.assertEqual(response.status_code, 200)
        params = DeviceLogTask.objects.get(task_id=response.data['task_id']).params
        self.assertEqual(params['lines'], 500)
        self.assertEqual(datetime.fromisoformat(params['start_time']), now - timedelta(hours=1))

    def test_log_task_writes_from_stale_device_do_not_overwrite_heartbeat_config(self):
        stale_device = Device.objects.get(pk=self.device.pk)
        response = self.client.post(self.device_url('heartbeat'),
                                    {'agent_version': '1.7.4', 'frp_config_version': 27}, format='json')
        self.assertEqual(response.status_code, 200)
        task_id = create_log_task(stale_device, 'read', {'date': '2026-11-18', 'file': 'synthetic.log'})
        self.client.get(self.device_url('pending_log_tasks'))
        response = self.client.post(self.device_url('report_log_task'),
                                    {'task_id': task_id, 'status': 'completed', 'result': {'content': 'synthetic'}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.config, {'agent_version': '1.7.4', 'frp_config_version': 27, 'preserved': {'value': 42}})
        self.assertEqual(DeviceLogTask.objects.get(task_id=task_id).status, 'completed')

    def test_device_list_detail_and_heartbeat_exclude_legacy_task_payload(self):
        config = {**self.device.config, 'log_tasks': {'legacy-id': {'result': {'content': 'synthetic-legacy-content'}}}}
        Device.objects.filter(pk=self.device.pk).update(config=config)
        responses = [self.client.get('/api/devices/'), self.client.get(f'/api/devices/{self.device.device_id}/'),
                     self.client.post(self.device_url('heartbeat'), {'agent_version': '1.7.3'}, format='json')]
        for response in responses:
            self.assertEqual(response.status_code, 200)
            rendered = json.dumps(response.data, default=str)
            self.assertNotIn('log_tasks', rendered)
            self.assertNotIn('synthetic-legacy-content', rendered)
        detail = self.client.get(f'/api/devices/{self.device.device_id}/').data
        self.assertEqual(detail['config']['preserved'], {'value': 42})
        self.device.refresh_from_db()
        self.assertIn('log_tasks', self.device.config)


class LegacyAgentLogRequestTests(LogAPITestCase):
    def setUp(self):
        super().setUp()
        Device.objects.filter(pk=self.device.pk).update(config={'agent_version': '1.7.2'})

    def test_legacy_list_read_download_reject_invalid_dates_without_creating_tasks(self):
        invalid_dates = ['2026-02-30', '2026-13-01', '../2026-11-18', '/2026-11-18',
                         '2026-11-18/child', '2026-11-18\\child', '2026-11-18:extra', '2026-11-18\x00']
        for action, extra in [('list_logs', {}), ('read_log', {'file': 'synthetic.log'}),
                              ('download_log', {'files': ['synthetic.log']})]:
            for date in invalid_dates:
                with self.subTest(action=action, date=repr(date)):
                    response = self.client.post(self.device_url(action), {'date': date, **extra}, format='json')
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertFalse(DeviceLogTask.objects.exists())

    def test_legacy_read_download_reject_unsafe_filenames_without_creating_tasks(self):
        filenames = ['.', '..', '../synthetic.log', '/tmp/synthetic.log', 'nested/synthetic.log',
                     'nested\\synthetic.log', 'C:\\synthetic.log', 'synthetic.log:stream', 'synthetic\x00.log']
        for filename in filenames:
            for action, names in [('read_log', {'file': filename}), ('download_log', {'files': ['safe.log', filename]})]:
                with self.subTest(action=action, filename=repr(filename)):
                    response = self.client.post(self.device_url(action), {'date': '2026-11-18', **names}, format='json')
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertFalse(DeviceLogTask.objects.exists())

    def test_legacy_download_rejects_more_than_100_files_without_creating_task(self):
        response = self.client.post(self.device_url('download_log'),
                                    {'date': '2026-11-18', 'files': [f'synthetic-{index}.log' for index in range(101)]}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DeviceLogTask.objects.exists())

    def test_legacy_read_rejects_invalid_line_limits_without_creating_task(self):
        for lines in (2001, -1, 'invalid'):
            with self.subTest(lines=lines):
                response = self.client.post(self.device_url('read_log'),
                                            {'date': '2026-11-18', 'file': 'synthetic.log', 'lines': lines}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertFalse(DeviceLogTask.objects.exists())

    def test_legacy_read_zero_and_default_are_bounded_and_valid_lines_preserved(self):
        for extra, expected in [({}, 2000), ({'lines': 0}, 2000), ({'lines': 1}, 1),
                                ({'lines': 500}, 500), ({'lines': 2000}, 2000)]:
            with self.subTest(extra=extra):
                response = self.client.post(self.device_url('read_log'),
                                            {'date': '2026-11-18', 'file': 'synthetic.log', **extra}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                task = DeviceLogTask.objects.get(task_id=response.data['task_id'])
                self.assertEqual((task.task_type, task.status), ('read', 'pending'))
                self.assertEqual(task.params['lines'], expected)
                self.assertEqual((task.params['date'], task.params['file']), ('2026-11-18', 'synthetic.log'))

    def test_legacy_list_and_download_accept_valid_date_and_100_filenames(self):
        for payload in ({}, {'date': '2026-11-18'}):
            response = self.client.post(self.device_url('list_logs'), payload, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(DeviceLogTask.objects.get(task_id=response.data['task_id']).params, payload)
        files = [f'synthetic-{index}.log' for index in range(100)]
        response = self.client.post(self.device_url('download_log'), {'date': '2026-11-18', 'files': files}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        task = DeviceLogTask.objects.get(task_id=response.data['task_id'])
        self.assertEqual((task.task_type, task.params), ('download', {'date': '2026-11-18', 'files': files}))


@override_settings(SYSTEM_LOG_RETENTION_DAYS=90)
class LogRetentionTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 11, 18, 4, tzinfo=dt_timezone.utc)
        for target, value in [('management.system_logs.timezone.now', self.now),
                              ('management.system_logs.time.monotonic', 10000.0),
                              ('management.system_logs._last_cleanup', 0.0)]:
            patcher = patch(target, return_value=value) if target.endswith(('now', 'monotonic')) else patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, timestamp):
        return SystemLog.objects.create(timestamp=timestamp, level='INFO', module='system', action='test', result='success')

    def test_ninety_day_cutoff_preserves_boundary_new_events_and_device_logs(self):
        cutoff = self.now - timedelta(days=90)
        expired = self.event(cutoff - timedelta(microseconds=1))
        boundary = self.event(cutoff)
        recent = self.event(cutoff + timedelta(microseconds=1))
        device = Device.objects.create(device_id='DEV-retention')
        uploaded = DeviceLog.objects.create(device=device, level='INFO', message='historical device log', timestamp=cutoff - timedelta(days=1))
        system_logs.cleanup_logs()
        self.assertFalse(SystemLog.objects.filter(pk=expired.pk).exists())
        self.assertSetEqual(set(SystemLog.objects.values_list('pk', flat=True)), {boundary.pk, recent.pk})
        self.assertTrue(DeviceLog.objects.filter(pk=uploaded.pk).exists())

    def test_retention_respects_hourly_cleanup_flag_and_runs_again_after_hour(self):
        system_logs.cleanup_logs()
        expired = self.event(self.now - timedelta(days=91))
        with patch('management.system_logs.time.monotonic', return_value=13599.0):
            system_logs.cleanup_logs()
        self.assertTrue(SystemLog.objects.filter(pk=expired.pk).exists())
        with patch('management.system_logs.time.monotonic', return_value=13600.0):
            system_logs.cleanup_logs()
        self.assertFalse(SystemLog.objects.filter(pk=expired.pk).exists())

    def test_old_terminal_tasks_removed_but_pending_processing_and_recent_kept(self):
        device = Device.objects.create(device_id='DEV-task-retention')
        for state in ('completed', 'failed', 'pending', 'processing'):
            DeviceLogTask.objects.create(device=device, task_id=state, task_type='read', status=state,
                                         created_at=self.now - timedelta(days=8))
        DeviceLogTask.objects.create(device=device, task_id='boundary', task_type='read', status='completed',
                                     created_at=self.now - timedelta(days=7))
        system_logs.cleanup_logs()
        self.assertSetEqual(set(DeviceLogTask.objects.values_list('task_id', flat=True)), {'pending', 'processing', 'boundary'})


class LegacyLogTaskMigrationTests(TransactionTestCase):
    migrate_from = [('management', '0013_systemlog_devicelogtask')]
    migrate_to = [('management', '0014_move_legacy_log_tasks')]

    def test_forward_reverse_forward_preserves_result_updated_by_legacy_agent(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        device_model = apps.get_model('management', 'Device')
        task_id = '1700000000099'
        legacy = dict(task_type='read', params={'date': '2026-11-18', 'file': 'synthetic.log'},
                      status='pending', result={}, error_message='', created_at='2026-11-18T01:00:00+00:00', completed_at=None)
        device = device_model.objects.create(device_id='DEV-rollback',
                                              config={'preserved': {'value': 42}, 'log_tasks': {task_id: legacy}})
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        migrated = apps.get_model('management', 'DeviceLogTask').objects.get(device_id=device.pk, task_id=task_id)
        original_pk = migrated.pk
        self.assertEqual((migrated.status, migrated.result), ('pending', {}))
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        device_model = apps.get_model('management', 'Device')
        rolled_back = device_model.objects.get(pk=device.pk)
        self.assertEqual(rolled_back.config['log_tasks'][task_id]['status'], 'pending')
        completed_at = '2026-11-18T01:01:00+00:00'
        rolled_back.config['log_tasks'][task_id].update(
            status='completed', result={'content': 'result produced after rollback'}, completed_at=completed_at,
        )
        rolled_back.save(update_fields=['config'])
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        task_model = apps.get_model('management', 'DeviceLogTask')
        task = task_model.objects.get(device_id=device.pk, task_id=task_id)
        self.assertEqual((task.pk, task.status, task.result),
                         (original_pk, 'completed', {'content': 'result produced after rollback'}))
        self.assertEqual(task.completed_at, datetime.fromisoformat(completed_at))
        self.assertEqual(task.params, legacy['params'])
        self.assertEqual(task_model.objects.filter(device_id=device.pk, task_id=task_id).count(), 1)
        self.assertEqual(apps.get_model('management', 'Device').objects.get(pk=device.pk).config, {'preserved': {'value': 42}})

    def test_migration_preserves_ids_status_results_timestamps_and_unrelated_config(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        # Restore the schema even if a migration assertion fails.
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        old_device = apps.get_model('management', 'Device')
        legacy_tasks = {
            '1700000000001': dict(task_type='read', params={'file': 'synthetic.log'}, status='completed',
                                  result={'content': 'preserved result'}, error_message='',
                                  created_at='2026-11-17T01:00:00+00:00', completed_at='2026-11-17T01:01:00+00:00'),
            '1700000000002': dict(task_type='search', params={'keyword': 'synthetic'}, status='failed',
                                  result={'matches': []}, error_message='preserved failure',
                                  created_at='2026-11-17T02:00:00+00:00', completed_at='2026-11-17T02:01:00+00:00'),
            '1700000000003': dict(task_type='list', params={}, status='pending', result={},
                                  created_at='2026-11-17T03:00:00+00:00'),
            '1700000000004': dict(task_type='download', params={'files': ['synthetic.log']}, status='processing', result={},
                                  created_at='2026-11-17T04:00:00+00:00'),
        }
        preserved = {'agent_version': '1.7.2', 'frp_config_version': 12, 'nested': {'value': 42}}
        first = old_device.objects.create(device_id='DEV-legacy', config={**preserved, 'log_tasks': legacy_tasks})
        second = old_device.objects.create(device_id='DEV-legacy-second', config={'log_tasks': {'1700000000001': legacy_tasks['1700000000001']}})
        untouched = old_device.objects.create(device_id='DEV-no-legacy', config={'untouched': True})
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        new_device = apps.get_model('management', 'Device')
        task_model = apps.get_model('management', 'DeviceLogTask')
        self.assertEqual(task_model.objects.filter(device_id=first.pk).count(), 4)
        for task_id, original in legacy_tasks.items():
            with self.subTest(task_id=task_id):
                task = task_model.objects.get(device_id=first.pk, task_id=task_id)
                for field in ('task_type', 'params', 'status', 'result'):
                    self.assertEqual(getattr(task, field), original[field])
                self.assertEqual(task.error_message, original.get('error_message', ''))
                self.assertEqual(task.created_at, datetime.fromisoformat(original['created_at']))
                expected_end = datetime.fromisoformat(original['completed_at']) if original.get('completed_at') else None
                self.assertEqual(task.completed_at, expected_end)
        self.assertEqual(task_model.objects.filter(device_id=second.pk, task_id='1700000000001').count(), 1)
        self.assertEqual(new_device.objects.get(pk=first.pk).config, preserved)
        self.assertEqual(new_device.objects.get(pk=second.pk).config, {})
        self.assertEqual(new_device.objects.get(pk=untouched.pk).config, {'untouched': True})
