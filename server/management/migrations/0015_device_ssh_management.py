import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('management', '0014_move_legacy_log_tasks'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DeviceSshManagement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('credential_hash', models.CharField(blank=True, max_length=64)),
                ('frp_publickey_locked', models.BooleanField(default=False)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('reported_state', models.JSONField(blank=True, default=dict)),
                ('reported_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('device', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ssh_management',
                    to='management.device',
                )),
            ],
        ),
        migrations.CreateModel(
            name='DeviceSshTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(max_length=32, unique=True)),
                ('task_type', models.CharField(max_length=40)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(
                    choices=[
                        ('pending', '待领取'), ('processing', '执行中'),
                        ('completed', '已完成'), ('failed', '失败'), ('expired', '已过期'),
                    ],
                    default='pending', max_length=20,
                )),
                ('result', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField()),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('device', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ssh_management_tasks',
                    to='management.device',
                )),
                ('requested_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='requested_device_ssh_tasks', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'permissions': [('manage_device_ssh', 'Can manage device SSH access')],
            },
        ),
        migrations.AddIndex(
            model_name='devicesshtask',
            index=models.Index(fields=['device', 'status', 'created_at'], name='mgmt_sshdev_status_idx'),
        ),
        migrations.AddIndex(
            model_name='devicesshtask',
            index=models.Index(fields=['expires_at', 'status'], name='mgmt_ssh_exp_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='devicesshtask',
            constraint=models.UniqueConstraint(
                fields=['device'], condition=models.Q(status__in=['pending', 'processing']),
                name='mgmt_ssh_one_open_task',
            ),
        ),
    ]
