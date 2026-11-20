"""Preserve existing Agent task IDs and results when isolating log task storage."""
from django.db import migrations
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def task_datetime(value, required=False):
    if value is None:
        return timezone.now() if required else None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError('Invalid legacy log task timestamp; inspect Device.config before retrying migration')
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def forwards(apps, schema_editor):
    Device = apps.get_model('management', 'Device')
    Task = apps.get_model('management', 'DeviceLogTask')
    alias = schema_editor.connection.alias
    for device in Device.objects.using(alias).iterator(chunk_size=100):
        config = device.config
        if not isinstance(config, dict) or 'log_tasks' not in config:
            continue
        tasks = config['log_tasks']
        if not isinstance(tasks, dict):
            raise ValueError(f'Invalid legacy log_tasks for device {device.pk}; nothing has been discarded')
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                raise ValueError(f'Invalid legacy log task {task_id} for device {device.pk}')
            # After an application rollback, legacy JSON may contain newer completion data.
            Task.objects.using(alias).update_or_create(
                device_id=device.pk, task_id=str(task_id),
                defaults={
                    'task_type': task.get('task_type', 'read'), 'params': task.get('params', {}),
                    'status': task.get('status', 'pending'), 'result': task.get('result', {}),
                    'error_message': task.get('error_message', ''),
                    'created_at': task_datetime(task.get('created_at'), required=True),
                    'completed_at': task_datetime(task.get('completed_at')),
                },
            )
        Device.objects.using(alias).filter(pk=device.pk).update(
            config={key: value for key, value in config.items() if key != 'log_tasks'},
        )


def backwards(apps, schema_editor):
    Device = apps.get_model('management', 'Device')
    Task = apps.get_model('management', 'DeviceLogTask')
    alias = schema_editor.connection.alias
    for device in Device.objects.using(alias).iterator(chunk_size=100):
        config = dict(device.config or {})
        tasks = config.setdefault('log_tasks', {})
        for task in Task.objects.using(alias).filter(device_id=device.pk).iterator(chunk_size=100):
            tasks[task.task_id] = {
                'task_type': task.task_type, 'params': task.params, 'status': task.status,
                'result': task.result, 'error_message': task.error_message,
                'created_at': task.created_at.isoformat(),
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            }
        Device.objects.using(alias).filter(pk=device.pk).update(config=config)


class Migration(migrations.Migration):
    dependencies = [('management', '0013_systemlog_devicelogtask')]
    operations = [migrations.RunPython(forwards, backwards)]
