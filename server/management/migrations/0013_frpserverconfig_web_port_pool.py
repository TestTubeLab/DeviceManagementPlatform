from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0012_alter_device_health_check_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='frpserverconfig',
            name='web_port_pool_start',
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text='Web端口池起始（留空表示不启用）',
            ),
        ),
        migrations.AddField(
            model_name='frpserverconfig',
            name='web_port_pool_end',
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text='Web端口池结束（留空表示不启用）',
            ),
        ),
    ]
