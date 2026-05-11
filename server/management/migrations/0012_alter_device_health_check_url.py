from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0011_device_hardware_fingerprint'),
    ]

    operations = [
        migrations.AlterField(
            model_name='device',
            name='health_check_url',
            field=models.CharField(
                blank=True,
                default='http://localhost:8088/api/',
                max_length=200,
                verbose_name='健康检查URL',
            ),
        ),
    ]
