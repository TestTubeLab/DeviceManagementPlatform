from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def request_confirmation_for_reserved_disabled_devices(apps, schema_editor):
    device_model = apps.get_model('management', 'Device')
    device_model.objects.filter(frp_enabled=False).filter(
        Q(frp_ssh_port__isnull=False) | Q(frp_web_port__isnull=False),
    ).update(frp_stop_requested_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ('management', '0015_device_ssh_management'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='frp_public_access',
            field=models.BooleanField(default=False, verbose_name='允许FRP端口公网直连'),
        ),
        migrations.AddField(
            model_name='device',
            name='frp_stop_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='frpserverconfig',
            name='firewall_revision',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(request_confirmation_for_reserved_disabled_devices, migrations.RunPython.noop),
    ]
