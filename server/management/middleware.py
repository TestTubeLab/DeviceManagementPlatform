"""Record scoped platform actions and request failures using Django middleware."""
import traceback

from .models import Device, Project
from .system_logs import record_system_log, request_secrets


MODULES = {
    'DeviceViewSet': 'device', 'ProjectViewSet': 'project',
    'DockerImageViewSet': 'image', 'CodePackageViewSet': 'package',
    'DeploymentTaskViewSet': 'deployment', 'UpdateTaskViewSet': 'deployment',
    'ProjectDeploymentViewSet': 'deployment', 'FrpManagementViewSet': 'frp',
}
ASYNC_ACTIONS = {
    'restart', 'batch_update', 'apply_config', 'rollback_config', 'update_agent',
    'setup_factory_config', 'push_to_device', 'deploy_to_devices',
}
SKIP_ACTIONS = {
    'register', 'heartbeat', 'upload_logs', 'fetch_frp_config', 'report_frp_status',
    'pending_config', 'pending_system_tasks', 'pending_log_tasks', 'report_log_task',
    'list_logs', 'read_log', 'search_logs', 'download_log', 'service_logs',
}
CALLBACK_ACTIONS = {'config_result', 'progress', 'update_progress', 'report_system_task'}


class OperationLogMiddleware:
    """Audit whitelisted management operations, not high-frequency polling traffic."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self.record_response(request, response)
        except Exception:
            # Auditing must also tolerate unexpected payloads and snapshot lookup failures.
            from .system_logs import logger
            logger.error('System log request instrumentation failed')
        return response

    def record_response(self, request, response):
        if not request.path.startswith('/api/') or getattr(request, '_audit_exception', False):
            return response
        context = getattr(request, '_audit_context', {})
        action = context.get('action', '')
        module = context.get('module', '')
        auth_action = context.get('url_name') in ('user_login', 'user_logout')
        request_error = response.status_code >= 500
        if not request_error and (
            request.method not in ('POST', 'PUT', 'PATCH', 'DELETE')
            or action in SKIP_ACTIONS or (not module and not auth_action)
        ):
            return response
        drf_request = (getattr(response, 'renderer_context', None) or {}).get('request')
        # Only inspect an already-parsed DRF body: no second reads of uploads or auth failures.
        data = getattr(drf_request, '_full_data', {})
        if not isinstance(data, dict):
            data = {}
        payload = getattr(response, 'data', {})
        if not isinstance(payload, dict):
            payload = {}
        if not context.get('target') and module and payload.get('name'):
            context['target'] = f"{str(payload['name'])[:200]} ({payload.get('id', '')})"
        user = getattr(request, 'user', None)
        actor = user.get_username() if user and user.is_authenticated else 'anonymous'
        if auth_action:
            module, action = 'auth', context['url_name']
            actor = actor if actor != 'anonymous' else str(data.get('username', 'anonymous'))[:150]
        failed = response.status_code >= 400 or bool(payload.get('error'))
        outcome = 'failed' if failed else ('submitted' if action in ASYNC_ACTIONS else 'success')
        task_id = str(payload.get('task_id') or payload.get('config_id') or '')
        if not failed and action == 'create' and module == 'deployment':
            outcome = 'submitted' if payload.get('status') in ('pending', 'deploying', 'downloading') else 'success'
            task_id = str(payload.get('id', ''))
            if payload.get('device'):
                device_id_value = Device.objects.filter(pk=payload['device']).values_list('device_id', flat=True).first()
                context['device_id'] = device_id_value or ''
        event_key = None
        device_id = context.get('device_id', '')
        if action in ('deploy_to_devices', 'push_to_device') and not failed:
            # A batch response can mix accepted and rejected devices despite HTTP 200.
            accepted = payload.get('deployments', []) if action == 'deploy_to_devices' else payload.get('created_tasks', [])
            for deployment in accepted:
                record_system_log(
                    level='INFO', module='deployment', action=action, actor=actor,
                    target=context.get('target', request.path), result='submitted',
                    message='部署任务已下发', device_id=deployment['device_id'],
                    task_id=str(deployment.get('deployment_id') or deployment.get('task_id')),
                )
            for rejected in payload.get('failed_devices', []):
                record_system_log(
                    secrets=request_secrets(data), level='ERROR', module='deployment', action=action,
                    actor=actor, target=context.get('target', request.path), result='failed',
                    message='部署任务下发失败', device_id=str(rejected.get('device_id', '')),
                    detail=rejected.get('error', ''),
                )
            return response
        if action in CALLBACK_ACTIONS and not failed:
            terminal = data.get('status')
            if action == 'config_result':
                terminal = 'completed' if data.get('success') else 'failed'
            if terminal not in ('completed', 'failed', 'success', 'rolled_back'):
                return response
            outcome = 'success' if terminal in ('completed', 'success') else 'failed'
            task_id = str(data.get('task_id') or data.get('config_id') or context.get('pk', ''))
            # Legacy progress callbacks without IDs cannot be deduplicated across distinct jobs.
            if task_id:
                event_key = f"{context.get('namespace', module)}:{action}:{device_id}:{task_id}:{outcome}"
            actor = 'Agent'
        message = {'submitted': '操作请求已下发', 'success': '操作成功', 'failed': '操作失败'}[outcome]
        if action == 'service_control':
            message = f"FRP 服务 {data.get('action', '')}: {outcome}"
        # Only bounded error text, never serialized responses (which may contain FRP tokens).
        detail = payload.get('error') or payload.get('detail') or ''
        if action in CALLBACK_ACTIONS:
            detail = data.get('error_message') or data.get('error') or detail
        if request_error and not module:
            module = 'system'
        record_system_log(
            secrets=request_secrets(data), level='ERROR' if outcome == 'failed' else 'INFO',
            module=module or 'system', action=action or 'request', actor=actor,
            target=context.get('target') or request.path[:300], result=outcome,
            message=message, detail=f'HTTP {response.status_code}\n{detail}',
            device_id=device_id, task_id=task_id, event_key=event_key,
        )
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        cls = getattr(view_func, 'cls', None)
        module = MODULES.get(getattr(cls, '__name__', ''), '')
        action = getattr(view_func, 'actions', {}).get(request.method.lower(), '')
        match = request.resolver_match
        context = {
            'module': module, 'action': action, 'url_name': match.url_name,
            'namespace': getattr(cls, '__name__', ''),
            'pk': str(view_kwargs.get('pk', '')), 'device_id': str(view_kwargs.get('device_id', '')),
        }
        request._audit_context = context
        if action in SKIP_ACTIONS:
            return None
        try:
            self.snapshot_target(context, cls, view_kwargs, request.method)
        except Exception:
            from .system_logs import logger
            logger.error('System log target snapshot unavailable')

    def snapshot_target(self, context, cls, view_kwargs, method):
        """Best-effort target snapshots must not change invalid-ID handling of a view."""
        module = context['module']
        # Snapshot deleted objects before the view runs; no request body is inspected here.
        if module in ('device', 'project') and method != 'GET':
            model, lookup, value = (
                (Device, 'device_id', context['device_id']) if module == 'device'
                else (Project, 'pk', view_kwargs.get('pk'))
            )
            if value:
                obj = model.objects.filter(**{lookup: value}).only('name').first()
                if obj:
                    context['target'] = f'{obj.name} ({value})'
        elif module and method != 'GET' and view_kwargs.get('pk'):
            queryset = getattr(cls, 'queryset', None)
            if queryset is not None:
                obj = queryset.filter(pk=view_kwargs['pk']).first()
                if obj:
                    name = getattr(obj, 'name', None) or getattr(obj, 'deployed_version', None) or str(obj.pk)
                    context['target'] = f'{name} ({obj.pk})'
                    if getattr(obj, 'device_id', None):
                        context['device_id'] = obj.device.device_id

    def process_exception(self, request, exception):
        if not request.path.startswith('/api/'):
            return None
        request._audit_exception = True
        context = getattr(request, '_audit_context', {})
        # Stack locations help diagnosis without capturing local variables or exception values.
        detail = '\n'.join(
            f'{frame.filename}:{frame.lineno} in {frame.name}'
            for frame in traceback.extract_tb(exception.__traceback__)
        )
        user = getattr(request, 'user', None)
        record_system_log(
            level='ERROR', module=context.get('module') or 'system',
            action=context.get('action') or 'request',
            actor=user.get_username() if user and user.is_authenticated else 'anonymous',
            target=context.get('target') or request.path[:300], result='failed',
            message=f'{type(exception).__name__}: 后台请求异常', detail=detail,
            device_id=context.get('device_id', ''),
        )
        return None
