from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('management', '0012_alter_device_health_check_url')]

    operations = [
        migrations.CreateModel(
            name='SystemLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('level', models.CharField(choices=[('DEBUG', '调试'), ('INFO', '信息'), ('WARNING', '警告'), ('ERROR', '错误'), ('CRITICAL', '严重')], max_length=10)),
                ('module', models.CharField(max_length=40)),
                ('action', models.CharField(max_length=80)),
                ('actor', models.CharField(blank=True, max_length=150)),
                ('target', models.CharField(blank=True, max_length=300)),
                ('result', models.CharField(choices=[('submitted', '已下发'), ('success', '成功'), ('failed', '失败')], max_length=12)),
                ('message', models.TextField(blank=True)),
                ('detail', models.TextField(blank=True)),
                ('device_id', models.CharField(blank=True, max_length=100)),
                ('task_id', models.CharField(blank=True, max_length=100)),
                ('event_key', models.CharField(blank=True, max_length=200, null=True, unique=True)),
            ],
            options={
                'ordering': ['-timestamp', '-id'],
                'indexes': [models.Index(fields=['module', '-timestamp'], name='syslog_module_time')],
            },
        ),
        migrations.CreateModel(
            name='DeviceLogTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(max_length=100)),
                ('task_type', models.CharField(max_length=20)),
                ('params', models.JSONField(default=dict)),
                ('status', models.CharField(default='pending', max_length=12)),
                ('result', models.JSONField(default=dict)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='management.device')),
            ],
            options={
                'indexes': [models.Index(fields=['device', 'status', 'created_at'], name='devlogtask_state_time')],
                'constraints': [models.UniqueConstraint(fields=('device', 'task_id'), name='unique_device_log_task')],
            },
        ),
    ]
