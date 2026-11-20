"""Persistent log task lifecycle used by existing and upgraded Agents."""
import json
import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import DeviceLog, DeviceLogTask


class LogFileName(serializers.CharField):
    """The server also protects older Agents that lack path containment checks."""

    def to_internal_value(self, data):
        name = super().to_internal_value(data)
        if name in ('.', '..') or any(char in name for char in '/\\:\x00'):
            raise serializers.ValidationError('日志文件必须是文件名，不能包含路径')
        return name


class BusinessLogRequest(serializers.Serializer):
    date = serializers.DateField(required=False, input_formats=['%Y-%m-%d'])
    file = LogFileName(required=False, max_length=255)
    files = serializers.ListField(child=LogFileName(max_length=255), required=False, min_length=1, max_length=100)
    lines = serializers.IntegerField(required=False, min_value=0, max_value=2000)
    tail = serializers.BooleanField(required=False)
    keyword = serializers.CharField(required=False, max_length=200)
    start_date = serializers.DateField(required=False, allow_null=True, input_formats=['%Y-%m-%d'])
    end_date = serializers.DateField(required=False, allow_null=True, input_formats=['%Y-%m-%d'])
    level = serializers.ChoiceField(choices=DeviceLog.LEVEL_CHOICES, required=False, allow_blank=True, allow_null=True)
    case_sensitive = serializers.BooleanField(required=False)

    def validate(self, attrs):
        task_type = self.context['task_type']
        required = {'list': (), 'read': ('date', 'file'), 'search': ('keyword',), 'download': ('date', 'files')}[task_type]
        for name in required:
            if not attrs.get(name):
                raise serializers.ValidationError({name: '此参数必填'})
        if attrs.get('start_date') and attrs.get('end_date') and attrs['start_date'] > attrs['end_date']:
            raise serializers.ValidationError('开始日期不能晚于结束日期')
        for field in ('date', 'start_date', 'end_date'):
            if attrs.get(field):
                attrs[field] = attrs[field].isoformat()
        if task_type == 'read':
            attrs['lines'] = attrs.get('lines') or 2000
        return attrs


class ServiceLogRequest(serializers.Serializer):
    source = serializers.ChoiceField(choices=['agent', 'frpc', 'docker', 'system'])
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)
    lines = serializers.IntegerField(default=500, min_value=1, max_value=2000)
    level = serializers.ChoiceField(choices=DeviceLog.LEVEL_CHOICES, required=False, allow_blank=True)
    keyword = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        attrs.setdefault('start_time', timezone.now() - timedelta(hours=1))
        if attrs.get('end_time') and attrs['start_time'] > attrs['end_time']:
            raise serializers.ValidationError('开始时间不能晚于结束时间')
        for field in ('start_time', 'end_time'):
            if field in attrs:
                attrs[field] = attrs[field].isoformat()
        return attrs


def supports_service_logs(device):
    version = str((device.config or {}).get('agent_version', '')).lstrip('v')
    try:
        parts = version.split('.')
        return len(parts) == 3 and all(part.isdigit() for part in parts) and tuple(map(int, parts)) >= (1, 7, 3)
    except ValueError:
        return False


def create_log_task(device, task_type, params):
    """Keep old HTTP contracts while removing shared JSON read/modify/write races."""
    if task_type in ('list', 'read', 'search', 'download'):
        serializer = BusinessLogRequest(data=params, context={'task_type': task_type})
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
    task = DeviceLogTask.objects.create(
        device=device, task_id=uuid.uuid4().hex, task_type=task_type, params=params,
    )
    from .system_logs import cleanup_logs, logger
    try:
        cleanup_logs()
    except Exception:
        logger.error('Log task retention cleanup failed')
    return task.task_id


def get_log_task(device, task_id):
    task = DeviceLogTask.objects.filter(device=device, task_id=str(task_id)).first()
    if task and task.task_type == 'journal' and task.status in ('pending', 'processing'):
        if task.created_at < timezone.now() - timedelta(seconds=120):
            DeviceLogTask.objects.filter(pk=task.pk, status__in=['pending', 'processing']).update(
                status='failed', error_message='日志查询已超时，请重新查询', completed_at=timezone.now(),
            )
            task.refresh_from_db()
    if not task:
        return None
    return {key: getattr(task, key) for key in (
        'task_id', 'task_type', 'status', 'result', 'error_message', 'created_at', 'completed_at',
    )}


def claim_log_tasks(device, limit=5):
    """Compare-and-set claims work on both SQLite and PostgreSQL."""
    now = timezone.now()
    DeviceLogTask.objects.filter(
        device=device, task_type='journal', status__in=['pending', 'processing'],
        created_at__lt=now - timedelta(seconds=120),
    ).update(status='failed', error_message='日志查询已超时，请重新查询', completed_at=now)
    tasks = []
    candidates = DeviceLogTask.objects.filter(device=device, status='pending').order_by('created_at', 'id')[:limit]
    for task in candidates:
        if DeviceLogTask.objects.filter(pk=task.pk, status='pending').update(status='processing'):
            tasks.append({'task_id': task.task_id, 'task_type': task.task_type, 'params': task.params})
    return tasks


def finish_log_task(device, task_id, task_status, result=None, error_message=''):
    """Terminal results are immutable; a retried report is acknowledged."""
    if task_status not in ('completed', 'failed'):
        raise ValidationError({'error': 'status 仅支持 completed/failed'})
    if not isinstance(result, dict):
        raise ValidationError({'error': 'result 必须是对象'})
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 24 * 1024 * 1024:
        raise ValidationError({'error': '日志结果超过大小限制'})
    get_log_task(device, task_id)  # Expired journal requests cannot become successful later.
    task = DeviceLogTask.objects.filter(device=device, task_id=str(task_id)).first()
    if not task:
        return False
    if task.task_type == 'journal' and len(str(result.get('content', '')).encode('utf-8')) > 512 * 1024:
        raise ValidationError({'error': '服务日志内容超过 512 KiB 限制'})
    # One conditional UPDATE is atomic without a read transaction that can deadlock
    # when SQLite upgrades concurrent heartbeat/log readers into writers.
    DeviceLogTask.objects.filter(pk=task.pk, status__in=['pending', 'processing']).update(
        status=task_status, result=result or {}, error_message=str(error_message)[:2000], completed_at=timezone.now(),
    )
    return True
