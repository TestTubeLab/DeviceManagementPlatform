"""设备 SSH 的管理权限、任务领取与可信回执。"""

import base64
import binascii
import hashlib
import logging
import re
import secrets
from datetime import timedelta
from hmac import compare_digest
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import get_authorization_header
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from .models import Device, DeviceSshManagement, DeviceSshTask


FINGERPRINT_PATTERN = r'^SHA256:[A-Za-z0-9+/]{43}$'
OPEN_TASK = ('pending', 'processing')
LIVE_FOR = timedelta(seconds=45)
TASK_TTL = timedelta(seconds=150)
logger = logging.getLogger(__name__)


def key_fingerprint(line):
    """仅接受无选项的 OpenSSH Ed25519 公钥，并返回规范指纹。"""
    parts = line.split(maxsplit=2)
    if len(parts) < 2 or parts[0] != 'ssh-ed25519' or not line.isprintable():
        raise serializers.ValidationError('请输入单行 SSH Ed25519 公钥，不可携带授权选项')
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error):
        raise serializers.ValidationError('公钥编码无效') from None
    if len(blob) != 51 or not blob.startswith(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 '):
        raise serializers.ValidationError('公钥格式无效')
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


class TaskInput(serializers.Serializer):
    operation = serializers.ChoiceField(choices=['add_key', 'activate', 'verify_key', 'confirm', 'remove_key'])
    public_key = serializers.CharField(max_length=512, required=False, write_only=True)
    fingerprint = serializers.RegexField(FINGERPRINT_PATTERN, max_length=50, required=False)
    operator_verified = serializers.BooleanField(required=False)

    def validate(self, data):
        action = data['operation']
        expected = {'operation', 'public_key'} if action == 'add_key' else {'operation', 'fingerprint'}
        if action in ('activate', 'confirm'):
            expected.add('operator_verified')
        if set(self.initial_data) != expected or set(data) != expected:
            raise serializers.ValidationError('任务参数与操作类型不匹配')
        if 'operator_verified' in data and not data.pop('operator_verified'):
            raise serializers.ValidationError('须先按提示验证恢复通道或独立登录')
        if action == 'add_key':
            data['fingerprint'] = key_fingerprint(data['public_key'])
        return data


class EnrollmentInput(serializers.Serializer):
    account = serializers.RegexField(r'^[a-z_][a-z0-9_-]{0,30}$')
    independent_recovery_verified = serializers.BooleanField()

    def validate_account(self, value):
        if value == 'root':
            raise serializers.ValidationError('SSH 纳管只允许使用非 root 账号')
        return value


class KeyState(serializers.Serializer):
    fingerprint = serializers.RegexField(FINGERPRINT_PATTERN, max_length=50)
    verified = serializers.BooleanField()


class AgentState(serializers.Serializer):
    account = serializers.RegexField(r'^[a-z_][a-z0-9_-]{0,30}$')
    independent_recovery_verified = serializers.BooleanField()
    mode = serializers.ChoiceField(choices=['legacy', 'pending', 'active', 'rolled_back'])
    local_password = serializers.ChoiceField(choices=['enabled', 'disabled', 'unknown'])
    frp_target = serializers.IntegerField(min_value=1, max_value=65535, allow_null=True)
    remote_publickey_only = serializers.BooleanField()
    host_fingerprints = serializers.ListField(
        child=serializers.RegexField(FINGERPRINT_PATTERN), max_length=10,
    )
    keys = KeyState(many=True, max_length=32)
    pending_fingerprint = serializers.RegexField(FINGERPRINT_PATTERN, allow_null=True)
    pending_until = serializers.DateTimeField(allow_null=True)
    login_observed = serializers.BooleanField()
    error = serializers.CharField(max_length=160, allow_blank=True)


def require_secure_channel(request):
    if not settings.DEVICE_SSH_MANAGEMENT_ENABLED:
        raise PermissionDenied('SSH 管理尚未启用')
    if not request.is_secure():
        raise PermissionDenied('SSH 管理要求 HTTPS')


def agent_access(request, device_id):
    require_secure_channel(request)
    auth = get_authorization_header(request).split()
    if len(auth) != 2 or auth[0].lower() != b'bearer' or not re.fullmatch(rb'[\w-]{43}', auth[1]):
        raise PermissionDenied('设备认证失败')
    digest = hashlib.sha256(auth[1]).hexdigest()
    record = DeviceSshManagement.objects.filter(device__device_id=device_id).first()
    if record is None or not compare_digest(record.credential_hash, digest):
        raise PermissionDenied('设备认证失败')
    return record


def operator_access(request):
    if not request.user.has_perm('management.manage_device_ssh'):
        raise PermissionDenied('需要设备 SSH 管理权限')
    require_secure_channel(request)


def expire_tasks(device_id, now):
    DeviceSshTask.objects.filter(
        device_id=device_id, status__in=OPEN_TASK, expires_at__lte=now,
    ).update(status='expired', completed_at=now, payload={})


def enrollment_url():
    """返回供设备校验证书并访问专用 API 的地址。"""
    url = settings.DEVICE_SSH_PUBLIC_URL
    try:
        endpoint = urlsplit(url)
        port = endpoint.port
    except ValueError:
        return ''
    if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username is not None
            or endpoint.query or endpoint.fragment or port == 0 or not endpoint.path
            or any(char.isspace() for char in url)):
        return ''
    return url


@api_view(['GET'])
@permission_classes([IsAdminUser])
def management_view(request, device_id):
    if not settings.DEVICE_SSH_MANAGEMENT_ENABLED:
        if not request.user.has_perm('management.manage_device_ssh'):
            raise PermissionDenied('需要设备 SSH 管理权限')
        # 平台上线与设备纳管分离；未启用时不返回设备状态，也不开放任务。
        return Response({'enabled': False, 'enrolled': False, 'online': False,
                         'reported_at': None, 'state': {}, 'tasks': []})
    operator_access(request)
    device = get_object_or_404(Device, device_id=device_id)
    record = DeviceSshManagement.objects.filter(device=device).first()
    now = timezone.now()
    expire_tasks(device.pk, now)
    tasks = [{
        'id': t.task_id, 'operation': t.task_type, 'status': t.status,
        'fingerprint': t.result.get('fingerprint'), 'error': t.error_message,
        'created_at': t.created_at, 'completed_at': t.completed_at, 'requested_by': t.requested_by_id,
    } for t in device.ssh_management_tasks.all()[:12]]
    return Response({
        'enabled': True,
        'enrollment_available': bool(enrollment_url() and not (record and record.frp_publickey_locked)),
        'enrolled': bool(record and record.credential_hash),
        'online': bool(record and record.credential_hash and record.last_seen_at
                       and record.last_seen_at + LIVE_FOR > now),
        'reported_at': record.reported_at if record else None,
        'state': record.reported_state if record else {},
        'tasks': tasks,
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
@transaction.atomic
def create_enrollment(request, device_id):
    """签发一次性设备凭据，供管理员经现有可信 SSH 通道安装到 Agent。"""
    operator_access(request)
    device = get_object_or_404(Device.objects.select_for_update(), device_id=device_id)
    data = EnrollmentInput(data=request.data)
    data.is_valid(raise_exception=True)
    server_url = enrollment_url()
    if not server_url:
        return Response({'detail': '平台未配置 HTTPS SSH 管理地址'}, status=503)

    record = DeviceSshManagement.objects.filter(device=device).first()
    if record and record.credential_hash:
        return Response({'detail': '设备已有 SSH 纳管凭据；若凭据遗失，请先通过可信控制台撤销后重新签发'}, status=409)
    if record and record.frp_publickey_locked:
        return Response({'detail': '设备已启用仅公钥策略，不能重新初始化纳管凭据'}, status=409)

    credential = secrets.token_urlsafe(32)
    digest = hashlib.sha256(credential.encode('ascii')).hexdigest()
    DeviceSshManagement.objects.update_or_create(device=device, defaults={
        'credential_hash': digest,
        'last_seen_at': None,
        'reported_at': None,
        'reported_state': {},
    })
    logger.info('设备 SSH 凭据已签发 device=%s operator=%s', device.device_id, request.user.pk)
    return Response({
        'device_id': device.device_id,
        'account': data.validated_data['account'],
        'credential': credential,
        'server_url': server_url,
        'independent_recovery_verified': data.validated_data['independent_recovery_verified'],
    }, status=201, headers={'Cache-Control': 'no-store'})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def create_task(request, device_id):
    operator_access(request)
    device = get_object_or_404(Device, device_id=device_id)
    data = TaskInput(data=request.data)
    data.is_valid(raise_exception=True)
    payload = dict(data.validated_data)
    action = payload.pop('operation')
    now = timezone.now()
    record = DeviceSshManagement.objects.filter(device=device).first()
    if not record or not record.credential_hash or not record.last_seen_at or record.last_seen_at + LIVE_FOR <= now:
        return Response({'detail': '设备未纳管或 SSH 管理 Agent 未在线'}, status=409)
    state = record.reported_state
    if state.get('error') and action not in ('add_key',):
        return Response({'detail': '设备 SSH 预检未通过，请先处理设备状态提示'}, status=409)
    if state.get('pending_fingerprint') and action != 'confirm':
        return Response({'detail': '请先确认或等待当前试登超时'}, status=409)
    if action == 'activate' and not state.get('independent_recovery_verified'):
        return Response({'detail': '设备未在本机核对独立恢复入口'}, status=409)
    if action in ('activate', 'verify_key', 'confirm'):
        if not device.frp_enabled or not device.frp_ssh_port:
            return Response({'detail': '设备尚未分配或启用 FRP SSH 端口'}, status=409)
        payload['external_port'] = device.frp_ssh_port
    if action == 'confirm' and (not state.get('login_observed')
                                or state.get('pending_fingerprint') != payload['fingerprint']):
        return Response({'detail': '尚未观察到该公钥的独立试登'}, status=409)
    expire_tasks(device.pk, now)
    try:
        with transaction.atomic():
            task = DeviceSshTask.objects.create(
                device=device, task_id=uuid4().hex, task_type=action, payload=payload,
                requested_by=request.user, expires_at=now + TASK_TTL,
                result={'fingerprint': payload['fingerprint']},
            )
    except IntegrityError:
        if DeviceSshTask.objects.filter(device=device, status__in=OPEN_TASK).exists():
            return Response({'detail': '该设备已有未结束的 SSH 任务'}, status=409)
        raise
    return Response({'id': task.task_id, 'status': task.status}, status=201)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def poll_task(request, device_id):
    record = agent_access(request, device_id)
    state = AgentState(data=request.data)
    state.is_valid(raise_exception=True)
    now = timezone.now()
    snapshot = dict(state.data)
    fields = {'last_seen_at': now, 'reported_at': now, 'reported_state': snapshot}
    if not record.frp_publickey_locked and snapshot['mode'] == 'active' and snapshot['remote_publickey_only']:
        # 仅用可信状态补偿已领取的管理员确认任务，不能单凭设备上报完成首次切换。
        verified = [key['fingerprint'] for key in snapshot['keys'] if key['verified']]
        if snapshot['frp_target'] == 2222 and verified and DeviceSshTask.objects.filter(
            device_id=record.device_id, task_type='confirm', status__in=('processing', 'expired'),
            started_at__gte=record.created_at, result__fingerprint__in=verified,
        ).exists():
            fields['frp_publickey_locked'] = True
    DeviceSshManagement.objects.filter(pk=record.pk, credential_hash=record.credential_hash).update(**fields)
    expire_tasks(record.device_id, now)
    task = DeviceSshTask.objects.filter(device_id=record.device_id, status='pending').first()
    if task and DeviceSshTask.objects.filter(
        pk=task.pk, status='pending', expires_at__gt=now, device__ssh_management__credential_hash=record.credential_hash,
    ).update(status='processing', started_at=now):
        return Response({'task': {
            'id': task.task_id, 'operation': task.task_type, 'payload': task.payload,
            'expires_at': task.expires_at,
        }})
    return Response({'task': None})


class Receipt(serializers.Serializer):
    id = serializers.RegexField(r'^[a-f0-9]{32}$')
    ok = serializers.BooleanField()
    error = serializers.CharField(max_length=160, allow_blank=True)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def report_task(request, device_id):
    record = agent_access(request, device_id)
    data = Receipt(data=request.data)
    data.is_valid(raise_exception=True)
    receipt = data.validated_data
    now = timezone.now()
    tasks = DeviceSshTask.objects.filter(
        device_id=record.device_id, task_id=receipt['id'],
        device__ssh_management__credential_hash=record.credential_hash,
    )
    task = get_object_or_404(tasks)
    result = 'completed' if receipt['ok'] else 'failed'
    if task.status == result:
        return Response(status=204)
    with transaction.atomic():
        if not tasks.filter(status='processing', expires_at__gt=now).update(
            status=result, completed_at=now, error_message=receipt['error'] if not receipt['ok'] else '', payload={},
        ):
            return Response({'detail': '任务未领取、已结束或已过期'}, status=409)
        if receipt['ok'] and task.task_type == 'confirm':
            DeviceSshManagement.objects.filter(pk=record.pk).update(frp_publickey_locked=True)
    return Response(status=204)
