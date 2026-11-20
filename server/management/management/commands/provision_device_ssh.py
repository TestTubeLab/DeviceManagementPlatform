"""通过可信控制台签发或撤销逐设备 SSH 管理凭据。"""

import hashlib
import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from management.models import Device, DeviceSshManagement, DeviceSshTask


class Command(BaseCommand):
    help = '签发一次性显示的设备凭据，或撤销已有 SSH 管理凭据'

    def add_arguments(self, parser):
        parser.add_argument('device_id')
        parser.add_argument('--revoke', action='store_true')

    @transaction.atomic
    def handle(self, device_id, revoke, **options):
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            raise CommandError('设备不存在') from None
        token = '' if revoke else secrets.token_urlsafe(32)
        DeviceSshManagement.objects.update_or_create(device=device, defaults={
            'credential_hash': hashlib.sha256(token.encode('ascii')).hexdigest() if token else '',
            'last_seen_at': None,
        })
        DeviceSshTask.objects.filter(device=device, status__in=('pending', 'processing')).update(
            status='expired', completed_at=timezone.now(), payload={},
        )
        self.stdout.write(token or '设备凭据已撤销；已生效的远程策略保持不变')
