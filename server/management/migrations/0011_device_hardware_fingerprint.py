from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0010_cleanup_disabled_frp_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='hardware_fingerprint',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True, verbose_name='硬件指纹'),
        ),
    ]
