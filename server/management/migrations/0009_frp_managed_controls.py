from django.db import migrations, models


def sync_existing_frp_enabled(apps, schema_editor):
    device_model = apps.get_model('management', 'Device')
    frp_config_model = apps.get_model('management', 'FrpServerConfig')

    frp_config = frp_config_model.objects.order_by('-is_active', 'id').first()
    if not frp_config:
        return

    for device in device_model.objects.all():
        port = getattr(device, 'frp_ssh_port', None)
        device.frp_enabled = bool(
            port and frp_config.port_pool_start <= port <= frp_config.port_pool_end
        )
        device.save(update_fields=['frp_enabled'])


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0008_add_frp_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='frp_enabled',
            field=models.BooleanField(default=True, verbose_name='启用FRP'),
        ),
        migrations.AddField(
            model_name='frpserverconfig',
            name='config_version',
            field=models.IntegerField(default=1, help_text='配置版本号'),
        ),
        migrations.RunPython(sync_existing_frp_enabled, migrations.RunPython.noop),
    ]
