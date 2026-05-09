from django.db import migrations


def cleanup_disabled_frp_state(apps, schema_editor):
    device_model = apps.get_model('management', 'Device')
    for device in device_model.objects.filter(frp_enabled=False):
        changed = False
        if device.frp_ssh_port is not None:
            device.frp_ssh_port = None
            changed = True
        if device.frp_web_port is not None:
            device.frp_web_port = None
            changed = True
        if device.frp_status != 'disconnected':
            device.frp_status = 'disconnected'
            changed = True
        if device.frp_error_message:
            device.frp_error_message = ''
            changed = True
        if changed:
            device.save(update_fields=['frp_ssh_port', 'frp_web_port', 'frp_status', 'frp_error_message'])


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0009_frp_managed_controls'),
    ]

    operations = [
        migrations.RunPython(cleanup_disabled_frp_state, migrations.RunPython.noop),
    ]
