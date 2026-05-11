"""
设备管理API视图
"""
import configparser
import hashlib
import os
import subprocess
import json
from io import StringIO
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse
from django.contrib.auth import authenticate
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from .models import (
    Device, DeploymentTask, UpdateTask, DeviceLog, DockerImage,
    CodePackage, Project, ProjectConfig, ProjectDeployment, FrpServerConfig
)
from .serializers import (
    DeviceSerializer, DeploymentTaskSerializer,
    UpdateTaskSerializer, DeviceLogSerializer, DockerImageSerializer,
    CodePackageSerializer, ProjectSerializer, ProjectConfigSerializer,
    ProjectDeploymentSerializer, FrpServerConfigSerializer, FrpDeviceSerializer
)

# Agent 最新版本号（每次更新 Agent 时需要同步修改）
AGENT_VERSION = "1.7.1"  # 修复设备身份识别和心跳 IP 刷新


def normalize_text(value):
    """标准化文本输入。"""
    if value is None:
        return ''
    text = str(value).replace('\x00', '').strip()
    return text


def normalize_mac_address(value):
    """标准化 MAC 地址。"""
    mac = normalize_text(value).lower()
    if not mac:
        return ''

    parts = mac.split(':')
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        return ''

    try:
        if all(int(part, 16) == 0 for part in parts):
            return ''
    except ValueError:
        return ''

    return ':'.join(parts)


def normalize_mac_addresses(values):
    """标准化 MAC 地址列表。"""
    if values is None:
        return []

    if isinstance(values, str):
        raw_values = values.split(',')
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = [values]

    normalized = []
    for value in raw_values:
        mac = normalize_mac_address(value)
        if mac and mac not in normalized:
            normalized.append(mac)
    return normalized


def build_device_id_from_fingerprint(hardware_fingerprint):
    """根据硬件指纹生成稳定的设备 ID。"""
    fingerprint = normalize_text(hardware_fingerprint)
    if not fingerprint:
        return ''
    digest = hashlib.md5(fingerprint.encode('utf-8')).hexdigest()[:8]
    return f"DEV-{digest}"


def registration_identity_matches(device, hardware_fingerprint, mac_candidates):
    """判断请求身份是否与现有设备记录一致。"""
    fingerprint = normalize_text(hardware_fingerprint)
    if fingerprint and device.hardware_fingerprint:
        return device.hardware_fingerprint == fingerprint

    if mac_candidates and device.mac_address:
        return device.mac_address in mac_candidates

    return True


def resolve_device_for_registration(requested_device_id, canonical_device_id, hardware_fingerprint, mac_candidates):
    """根据 device_id / 硬件指纹 / MAC 复用现有设备记录。"""
    queryset = Device.objects.select_for_update().order_by('-last_heartbeat', '-updated_at', 'id')

    for candidate_id in [requested_device_id, canonical_device_id]:
        if not candidate_id:
            continue
        device = queryset.filter(device_id=candidate_id).first()
        if device and registration_identity_matches(device, hardware_fingerprint, mac_candidates):
            return device

    fingerprint = normalize_text(hardware_fingerprint)
    if fingerprint:
        device = queryset.filter(hardware_fingerprint=fingerprint).first()
        if device:
            return device

    if mac_candidates:
        device = queryset.filter(mac_address__in=mac_candidates).first()
        if device:
            return device

    return None


# =============================================================================
# FRP 管理辅助函数
# =============================================================================
def get_default_frp_config():
    """从 settings 读取默认 FRP 配置，用于首次引导数据库记录。"""
    frp_cfg = getattr(settings, 'FRP_CONFIG', {})
    ssh_pool = frp_cfg.get('port_pools', {}).get('ssh', {})
    return {
        'server_addr': frp_cfg.get('server_addr', '127.0.0.1'),
        'server_port': frp_cfg.get('server_port', 7000),
        'token': frp_cfg.get('token', ''),
        'port_pool_start': ssh_pool.get('start', 6000),
        'port_pool_end': ssh_pool.get('end', 6999),
        'is_active': frp_cfg.get('enabled', True),
        'config_version': frp_cfg.get('config_version', 1),
        'description': '从 settings.FRP_CONFIG 自动初始化',
    }


def get_frp_config():
    """获取 FRP 配置（数据库为准，缺失时自动初始化）。"""
    config = FrpServerConfig.objects.order_by('-is_active', 'id').first()
    if config:
        return config

    return FrpServerConfig.objects.create(**get_default_frp_config())


def get_frp_runtime_settings():
    """FRP 服务运行时信息（容器名、宿主机配置目录）。"""
    return {
        'container_name': getattr(settings, 'FRP_SERVICE_CONTAINER', 'frps-service'),
        'config_dir': getattr(settings, 'FRP_HOST_CONFIG_DIR', '/root/frps-service'),
        'helper_image': getattr(settings, 'FRP_HELPER_IMAGE', 'alpine:latest'),
    }


def format_frp_allow_ports(start_port, end_port):
    """格式化 frps allow_ports 配置。"""
    if start_port == end_port:
        return str(start_port)
    return f"{start_port}-{end_port}"


def validate_frp_range(start_port, end_port):
    """校验 FRP 端口范围。"""
    if start_port > end_port:
        raise ValidationError({'port_pool_end': '端口池结束值必须大于等于起始值'})
    if start_port < 1 or end_port > 65535:
        raise ValidationError({'port_pool_start': '端口必须位于 1-65535 范围内'})


def get_used_frp_ports(exclude_device=None):
    """获取已使用的 FRP SSH 端口。"""
    queryset = Device.objects.filter(frp_enabled=True).exclude(frp_ssh_port__isnull=True)
    if exclude_device is not None:
        queryset = queryset.exclude(pk=exclude_device.pk)
    return set(queryset.values_list('frp_ssh_port', flat=True))


def release_device_frp_ports(device, save=True):
    """释放设备的 FRP 端口。"""
    device.frp_ssh_port = None
    device.frp_web_port = None
    device.frp_status = 'disconnected'
    device.frp_error_message = ''
    if save:
        device.save(update_fields=['frp_ssh_port', 'frp_web_port', 'frp_status', 'frp_error_message'])


def mark_device_pending_agent_update(device):
    """标记设备在下次心跳时更新 Agent。"""
    if not device.config:
        device.config = {}
    if device.config.get('agent_version') == AGENT_VERSION:
        return False
    if device.config.get('pending_agent_update'):
        return False
    device.config['pending_agent_update'] = True
    device.save(update_fields=['config'])
    return True


def should_disable_frp_for_device(device, frp_config=None):
    """判断设备是否需要停用 FRP。"""
    frp_config = frp_config or get_frp_config()
    return (not frp_config.is_active) or (not device.frp_enabled)


def is_frp_enabled_for_device(device, frp_config=None):
    """判断设备当前是否应该拿到 FRP 配置。"""
    frp_config = frp_config or get_frp_config()
    return frp_config.is_active and device.frp_enabled and bool(device.frp_ssh_port)


def allocate_frp_ssh_port(device, frp_config=None):
    """
    为设备分配 SSH 端口（幂等操作）
    - 如果已分配，直接返回
    - 如果未分配，从端口池中分配一个可用端口
    """
    if not device.frp_enabled:
        return None

    frp_config = frp_config or get_frp_config()

    if device.frp_ssh_port and frp_config.port_pool_start <= device.frp_ssh_port <= frp_config.port_pool_end:
        return device.frp_ssh_port

    if not frp_config.is_active:
        return None

    used_ports = get_used_frp_ports(exclude_device=device)

    for port in range(frp_config.port_pool_start, frp_config.port_pool_end + 1):
        if port not in used_ports:
            device.frp_ssh_port = port
            device.frp_status = 'disconnected'
            device.frp_error_message = ''
            device.save(update_fields=['frp_ssh_port', 'frp_status', 'frp_error_message'])
            return port

    return None


def plan_frp_port_assignments(frp_config):
    """根据当前端口池为启用 FRP 的设备规划端口。"""
    validate_frp_range(frp_config.port_pool_start, frp_config.port_pool_end)

    enabled_devices = list(Device.objects.filter(frp_enabled=True).order_by('created_at', 'id'))
    used_ports = set()
    assignments = {}
    pending_devices = []

    for device in enabled_devices:
        current_port = device.frp_ssh_port
        if (
            current_port
            and frp_config.port_pool_start <= current_port <= frp_config.port_pool_end
            and current_port not in used_ports
        ):
            assignments[device.pk] = current_port
            used_ports.add(current_port)
        else:
            pending_devices.append(device)

    next_port = frp_config.port_pool_start
    for device in pending_devices:
        while next_port in used_ports and next_port <= frp_config.port_pool_end:
            next_port += 1

        if next_port > frp_config.port_pool_end:
            raise ValidationError({
                'port_pool_end': f'端口池容量不足，当前启用 FRP 的设备数为 {len(enabled_devices)}'
            })

        assignments[device.pk] = next_port
        used_ports.add(next_port)
        next_port += 1

    return assignments


def apply_frp_port_assignments(frp_config, assignments=None):
    """应用 FRP 端口规划，同时清理已禁用设备的旧端口。"""
    assignments = assignments or plan_frp_port_assignments(frp_config)

    for device in Device.objects.filter(frp_enabled=False):
        if device.frp_ssh_port or device.frp_web_port:
            release_device_frp_ports(device)

    for device in Device.objects.filter(frp_enabled=True):
        expected_port = assignments.get(device.pk)
        if expected_port is None:
            continue

        update_fields = []
        if device.frp_ssh_port != expected_port:
            device.frp_ssh_port = expected_port
            device.frp_status = 'disconnected'
            device.frp_error_message = ''
            update_fields.extend(['frp_ssh_port', 'frp_status', 'frp_error_message'])

        if update_fields:
            device.save(update_fields=update_fields)


def build_frp_config_for_device(device, frp_config=None):
    """
    构建设备的 FRP 配置（供 Agent 拉取）
    返回 None 表示无配置
    """
    frp_config = frp_config or get_frp_config()

    if should_disable_frp_for_device(device, frp_config):
        return None

    ssh_port = device.frp_ssh_port or allocate_frp_ssh_port(device, frp_config=frp_config)
    if not ssh_port:
        return None

    return {
        'server_addr': frp_config.server_addr,
        'server_port': frp_config.server_port,
        'token': frp_config.token,
        'config_version': frp_config.config_version,
        'tunnels': {
            'ssh': {
                'type': 'tcp',
                'local_port': 22,
                'remote_port': ssh_port,
            }
        }
    }


def run_docker_command(args, input_text=None, timeout=60, check=True):
    """在平台容器中调用 Docker CLI。"""
    result = subprocess.run(
        ['docker', *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Docker 命令执行失败')
    return result


def run_frp_host_helper(command, input_text=None, timeout=60, check=True):
    """通过临时容器访问宿主机 FRP 配置目录。"""
    runtime = get_frp_runtime_settings()
    args = [
        'run', '--rm', '-i',
        '-v', f"{runtime['config_dir']}:/work",
        runtime['helper_image'],
        'sh', '-lc', command,
    ]
    return run_docker_command(args, input_text=input_text, timeout=timeout, check=check)


def get_frps_service_snapshot():
    """获取 FRP 服务容器状态。"""
    runtime = get_frp_runtime_settings()
    result = run_docker_command(
        ['inspect', runtime['container_name'], '--format', '{{json .State}}'],
        check=False
    )
    if result.returncode != 0:
        return {
            'container_name': runtime['container_name'],
            'status': 'missing',
            'running': False,
            'started_at': None,
            'error': (result.stderr or result.stdout).strip(),
        }

    try:
        state = json.loads(result.stdout.strip() or '{}')
    except json.JSONDecodeError as exc:
        return {
            'container_name': runtime['container_name'],
            'status': 'error',
            'running': False,
            'started_at': None,
            'error': str(exc),
        }

    return {
        'container_name': runtime['container_name'],
        'status': state.get('Status', 'unknown'),
        'running': bool(state.get('Running')),
        'started_at': state.get('StartedAt'),
        'error': state.get('Error') or '',
    }


def render_frps_ini(frp_config, existing_content=''):
    """根据数据库配置生成 frps.ini 内容。"""
    parser = configparser.RawConfigParser()
    parser.optionxform = str
    if existing_content.strip():
        parser.read_string(existing_content)

    if not parser.has_section('common'):
        parser.add_section('common')

    parser.set('common', 'bind_port', str(frp_config.server_port))
    parser.set('common', 'token', str(frp_config.token))
    parser.set(
        'common',
        'allow_ports',
        format_frp_allow_ports(frp_config.port_pool_start, frp_config.port_pool_end)
    )

    if not parser.has_option('common', 'log_file'):
        parser.set('common', 'log_file', '/var/log/frps/frps.log')
    if not parser.has_option('common', 'log_level'):
        parser.set('common', 'log_level', 'info')
    if not parser.has_option('common', 'log_max_days'):
        parser.set('common', 'log_max_days', '7')

    sio = StringIO()
    parser.write(sio)
    return sio.getvalue().strip() + '\n'


def write_frps_ini(content):
    """写入宿主机 FRP 配置文件，并保留备份。"""
    backup_name = f"frps-{timezone.now().strftime('%Y%m%d-%H%M%S')}.ini.bak"
    command = (
        'set -e; '
        'mkdir -p /work/backups; '
        f'if [ -f /work/frps.ini ]; then cp /work/frps.ini /work/backups/{backup_name}; fi; '
        'cat > /work/frps.ini.tmp; '
        'mv /work/frps.ini.tmp /work/frps.ini'
    )
    run_frp_host_helper(command, input_text=content, timeout=120)
    runtime = get_frp_runtime_settings()
    return os.path.join(runtime['config_dir'], 'backups', backup_name)


def sync_frps_service_config(frp_config, restart_if_running=True):
    """同步数据库配置到 frps.ini，必要时重启 FRP 服务。"""
    current_result = run_frp_host_helper('if [ -f /work/frps.ini ]; then cat /work/frps.ini; fi', check=False)
    current_content = current_result.stdout or ''
    new_content = render_frps_ini(frp_config, existing_content=current_content)
    backup_path = write_frps_ini(new_content)

    snapshot = get_frps_service_snapshot()
    if restart_if_running and snapshot['running']:
        runtime = get_frp_runtime_settings()
        restart_result = run_docker_command(['restart', runtime['container_name']], check=False, timeout=120)
        if restart_result.returncode != 0:
            write_frps_ini(current_content)
            run_docker_command(['restart', runtime['container_name']], check=False, timeout=120)
            raise RuntimeError(restart_result.stderr.strip() or restart_result.stdout.strip() or 'FRP 服务重启失败')

    return {
        'backup_path': backup_path,
        'service': get_frps_service_snapshot(),
    }


class DeviceViewSet(viewsets.ModelViewSet):
    """设备管理API"""
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = 'device_id'
    
    def get_permissions(self):
        """Agent 调用的接口不需要认证"""
        if self.action in [
            'register', 'heartbeat', 'retrieve', 'list', 'upload_logs',
            'pending_config', 'config_result', 'pending_log_tasks', 'report_log_task',
            'fetch_frp_config', 'report_frp_status', 'pending_system_tasks', 'report_system_task',
            'deployment', 'progress',
        ]:
            return [AllowAny()]
        return [IsAuthenticated()]
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        """
        设备注册接口
        POST /api/devices/register/
        Body: {
            "device_id": "dev_xxx",
            "mac_address": "00:11:22:33:44:55",
            "ip_address": "192.168.1.100",
            "hostname": "device-001"
        }
        """
        requested_device_id = normalize_text(request.data.get('device_id'))
        hardware_fingerprint = normalize_text(request.data.get('hardware_fingerprint'))
        canonical_device_id = build_device_id_from_fingerprint(hardware_fingerprint) or requested_device_id
        mac_address = normalize_mac_address(request.data.get('mac_address'))
        ip_address = normalize_text(request.data.get('ip_address'))
        mac_candidates = normalize_mac_addresses(request.data.get('mac_addresses'))
        if mac_address and mac_address not in mac_candidates:
            mac_candidates.insert(0, mac_address)
        
        if not requested_device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            device = resolve_device_for_registration(
                requested_device_id=requested_device_id,
                canonical_device_id=canonical_device_id,
                hardware_fingerprint=hardware_fingerprint,
                mac_candidates=mac_candidates,
            )
            created = device is None

            if created:
                device = Device.objects.create(
                    device_id=canonical_device_id or requested_device_id,
                    hardware_fingerprint=hardware_fingerprint or None,
                    mac_address=mac_address,
                    ip_address=ip_address,
                    status='waiting',
                )
            else:
                update_fields = []
                if hardware_fingerprint and device.hardware_fingerprint != hardware_fingerprint:
                    device.hardware_fingerprint = hardware_fingerprint
                    update_fields.append('hardware_fingerprint')
                if mac_address and device.mac_address != mac_address:
                    device.mac_address = mac_address
                    update_fields.append('mac_address')
                if ip_address and device.ip_address != ip_address:
                    device.ip_address = ip_address
                    update_fields.append('ip_address')

                device.last_heartbeat = timezone.now()
                update_fields.append('last_heartbeat')

                if update_fields:
                    device.save(update_fields=update_fields)

        frp_server_config = get_frp_config()
        frp_config = build_frp_config_for_device(device, frp_server_config)

        # 🔥 自动部署逻辑：如果设备配置了自动部署项目，创建部署任务
        auto_deploy_triggered = False
        if device.auto_deploy_project:
            # 检查是否已经有pending的部署任务
            existing_deployment = ProjectDeployment.objects.filter(
                device=device,
                project=device.auto_deploy_project,
                status__in=['pending', 'pulling_image', 'pulling_code', 'configuring', 'starting']
            ).exists()
            
            if not existing_deployment:
                # 创建自动部署任务
                ProjectDeployment.objects.create(
                    device=device,
                    project=device.auto_deploy_project,
                    deployed_version=device.auto_deploy_project.version,
                    status='pending',
                    message=f'设备上线，自动部署项目 {device.auto_deploy_project.name}'
                )
                auto_deploy_triggered = True
        
        return Response({
            "device_id": device.device_id,
            "status": device.status,
            "created": created,
            "auto_deploy_triggered": auto_deploy_triggered,
            "auto_deploy_project": device.auto_deploy_project.name if device.auto_deploy_project else None,
            # FRP 配置（Agent 据此配置 frpc）
            "frp_config": frp_config,
            "frp_disable_required": should_disable_frp_for_device(device, frp_server_config),
        })
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def heartbeat(self, request, device_id=None):
        """
        设备心跳接口（Agent调用，不需要认证）
        POST /api/devices/{device_id}/heartbeat/
        Body: {
            "version": "v1.0.3",
            "agent_version": "1.1.0",
            "cpu_usage": 45.2,
            "memory_usage": 62.5,
            "disk_usage": 38.7,
            "container_status": "running",
            "container_name": "middleware",
            "container_uptime": "2小时 30分钟",
            "service_status": "healthy",
            "service_response_time": 23
        }
        """
        device = self.get_object()
        
        # 更新设备状态
        device.current_version = request.data.get('version', device.current_version)
        device.cpu_usage = request.data.get('cpu_usage', 0)
        device.memory_usage = request.data.get('memory_usage', 0)
        device.disk_usage = request.data.get('disk_usage', 0)
        device.last_heartbeat = timezone.now()

        heartbeat_ip = normalize_text(request.data.get('ip_address'))
        if heartbeat_ip:
            device.ip_address = heartbeat_ip

        heartbeat_mac = normalize_mac_address(request.data.get('mac_address'))
        if heartbeat_mac:
            device.mac_address = heartbeat_mac

        heartbeat_fingerprint = normalize_text(request.data.get('hardware_fingerprint'))
        if heartbeat_fingerprint:
            device.hardware_fingerprint = heartbeat_fingerprint
        
        # 更新容器和服务状态
        device.container_status = request.data.get('container_status', device.container_status)
        device.container_name = request.data.get('container_name', device.container_name)
        device.container_uptime = request.data.get('container_uptime', device.container_uptime)
        device.service_status = request.data.get('service_status', device.service_status)
        device.service_response_time = request.data.get('service_response_time', device.service_response_time)
        device.last_health_check = timezone.now()
        
        # 保存 Agent 版本到 config 字段（无需数据库迁移）
        agent_version = request.data.get('agent_version')
        if agent_version:
            if not device.config:
                device.config = {}
            device.config['agent_version'] = agent_version
        
        # 保存 Agent 上报的 FRP 配置版本
        agent_frp_version = request.data.get('frp_config_version')
        if agent_frp_version is not None:
            if not device.config:
                device.config = {}
            device.config['frp_config_version'] = agent_frp_version
        
        # 更新在线状态：只要有心跳，就是在线（除非正在部署/更新）
        if device.status in ['offline', 'waiting']:
            device.status = 'online'
        
        device.save()
        
        # 检查是否有待执行的任务
        pending_deployment = DeploymentTask.objects.filter(
            device=device,
            status='pending'
        ).first()
        
        pending_update = UpdateTask.objects.filter(
            device=device,
            status='pending'
        ).first()
        
        response_data = {"command": "none"}
        
        # 检查是否需要更新 Agent（优先级最高）
        if device.config and device.config.get('pending_agent_update'):
            response_data = {"command": "update_agent"}
            # 清除标记
            device.config['pending_agent_update'] = False
            device.save()
        elif pending_deployment:
            response_data = {
                "command": "deploy",
                "task_id": pending_deployment.id,
                "deployment_config": {
                    "image": f"registry:5000/middleware:{pending_deployment.target_version}",
                    "config": pending_deployment.config,
                }
            }
        elif pending_update:
            response_data = {
                "command": "update",
                "task_id": pending_update.id,
                "version": pending_update.target_version,
            }
        
        # 🔥 FRP 配置版本检测：如果服务端配置版本更新，下发 update_frp 指令
        frp_cfg = get_frp_config()
        if should_disable_frp_for_device(device, frp_cfg):
            response_data['frp_disable_required'] = True
        elif device.frp_enabled:
            if not device.frp_ssh_port:
                allocate_frp_ssh_port(device, frp_config=frp_cfg)

        if is_frp_enabled_for_device(device, frp_cfg):
            server_frp_version = frp_cfg.config_version
            agent_frp_version = device.config.get('frp_config_version', 0) if device.config else 0
            
            if server_frp_version > agent_frp_version:
                # 配置版本变更，需要更新
                response_data['frp_update_required'] = True
                response_data['frp_config'] = build_frp_config_for_device(device, frp_cfg)
        
        return Response(response_data)
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def deployment(self, request, device_id=None):
        """
        获取部署指令（Agent调用，不需要认证）
        GET /api/devices/{device_id}/deployment/
        """
        device = self.get_object()
        
        # 检查是否有待执行的部署任务
        task = DeploymentTask.objects.filter(
            device=device,
            status='pending'
        ).first()
        
        if task:
            return Response({
                "status": "ready_to_deploy",
                "deployment_config": {
                    "image": f"registry:5000/middleware:{task.target_version}",
                    "config": task.config,
                }
            })
        else:
            return Response({"status": "waiting"})
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def progress(self, request, device_id=None):
        """
        上报部署/更新进度（Agent调用，不需要认证）
        POST /api/devices/{device_id}/progress/
        Body: {
            "status": "downloading",
            "progress": 50,
            "message": "正在下载镜像..."
        }
        """
        device = self.get_object()
        
        # 更新设备状态
        device.status = request.data.get('status', device.status)
        device.save()
        
        return Response({"status": "ok"})
    
    @action(detail=False, methods=['post'])
    def batch_update(self, request):
        """
        批量更新设备
        POST /api/devices/batch_update/
        Body: {
            "device_ids": ["dev_001", "dev_002"],
            "version": "v1.0.4"
        }
        """
        device_ids = request.data.get('device_ids', [])
        version = request.data.get('version')
        
        if not version:
            return Response(
                {"error": "version is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        tasks = []
        for device_id in device_ids:
            try:
                device = Device.objects.get(device_id=device_id)
                task = UpdateTask.objects.create(
                    device=device,
                    from_version=device.current_version,
                    target_version=version,
                    status='pending'
                )
                tasks.append(task.id)
            except Device.DoesNotExist:
                pass
        
        return Response({
            "created_tasks": len(tasks),
            "task_ids": tasks
        })
    
    @action(detail=True, methods=['post'])
    def restart(self, request, device_id=None):
        """
        重启设备服务
        POST /api/devices/{device_id}/restart/
        创建一个 ProjectDeployment 任务，task_type='restart'
        """
        device = self.get_object()
        
        # 获取容器名称（优先从最近部署的项目获取）
        container_name = 'middleware'  # 默认值
        last_deployment = ProjectDeployment.objects.filter(
            device=device, 
            task_type='deploy',
            status='completed'
        ).order_by('-created_at').first()
        
        if last_deployment and last_deployment.project:
            container_name = last_deployment.project.container_name or container_name
        
        # 创建重启任务（使用 ProjectDeployment 统一管理）
        task = ProjectDeployment.objects.create(
            device=device,
            project=last_deployment.project if last_deployment else None,
            task_type='restart',
            deployed_version=device.current_version or 'restart',
            status='pending',
            message=f'重启容器: {container_name}'
        )
        
        return Response({
            "status": "success",
            "message": "重启任务已创建",
            "task_id": task.id,
            "task_type": "restart"
        })
    
    def destroy(self, request, *args, **kwargs):
        """
        删除设备
        DELETE /api/devices/{device_id}/
        """
        device = self.get_object()
        device_id = device.device_id
        device.delete()
        
        return Response({
            "status": "success",
            "message": f"设备 {device_id} 已删除"
        })
    
    @action(detail=True, methods=['get'])
    def container_logs(self, request, device_id=None):
        """
        获取设备容器日志
        GET /api/devices/{device_id}/container_logs/
        """
        device = self.get_object()
        
        # 获取最近的日志记录
        logs = DeviceLog.objects.filter(device=device).order_by('-timestamp')[:100]
        
        return Response({
            "device_id": device.device_id,
            "logs": [
                {
                    "level": log.level,
                    "message": log.message,
                    "timestamp": log.timestamp.isoformat()
                }
                for log in logs
            ]
        })
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def upload_logs(self, request, device_id=None):
        """
        上传容器日志（Agent调用）
        POST /api/devices/{device_id}/upload_logs/
        Body: {
            "logs": "日志内容",
            "container_name": "middleware"
        }
        """
        device = self.get_object()
        logs_content = request.data.get('logs', '')
        container_name = request.data.get('container_name', 'middleware')
        
        if logs_content:
            # 解析日志内容，按行存储
            lines = logs_content.strip().split('\n')[-100:]  # 只保留最后100行
            
            # 清除旧日志（保留最近500条）
            old_logs = DeviceLog.objects.filter(device=device).order_by('-timestamp')[500:]
            DeviceLog.objects.filter(id__in=[l.id for l in old_logs]).delete()
            
            # 噪音日志模式（过滤已知的无用日志）
            noise_patterns = [
                'Not Found: /login',
                'GET /login HTTP',
                'GET /api/metrics HTTP/1.1" 302',
                'GET /api/health HTTP/1.1" 302',
            ]
            
            def is_noise_log(line):
                """判断是否为噪音日志"""
                return any(pattern in line for pattern in noise_patterns)
            
            # 存储新日志
            for line in lines:
                if line.strip() and not is_noise_log(line):
                    # 简单判断日志级别
                    level = 'INFO'
                    if '[ERROR]' in line or 'ERROR' in line:
                        level = 'ERROR'
                    elif '[WARNING]' in line or 'WARNING' in line:
                        level = 'WARNING'
                    elif '[DEBUG]' in line:
                        level = 'DEBUG'
                    elif '[CRITICAL]' in line or 'CRITICAL' in line:
                        level = 'CRITICAL'
                    
                    DeviceLog.objects.create(
                        device=device,
                        level=level,
                        message=line.strip()
                    )
        
        return Response({"status": "success", "message": "日志已上传"})
    
    @action(detail=True, methods=['post'])
    def update_agent(self, request, device_id=None):
        """
        触发设备更新 Agent（管理员调用）
        POST /api/devices/{device_id}/update_agent/
        设备下次心跳时会收到更新命令
        """
        device = self.get_object()
        
        # 标记需要更新 Agent
        if not device.config:
            device.config = {}
        device.config['pending_agent_update'] = True
        device.save()
        
        return Response({
            "status": "success",
            "message": f"已标记设备 {device_id} 需要更新 Agent，将在下次心跳时执行"
        })
    
    # ==================== 配置管理 API ====================
    @action(detail=True, methods=['get'])
    def current_config(self, request, device_id=None):
        """
        获取当前生效的配置
        GET /api/devices/{device_id}/current_config/
        """
        device = self.get_object()
        active_config = device.config_history.filter(is_active=True).first()
        
        if not active_config:
            # 返回默认配置
            return Response({
                "cameras": {
                    "样品盘": "192.168.31.201",
                    "前处理": "192.168.31.202",
                    "提取-纯化": "192.168.31.203",
                    "孔板传送": "192.168.31.204",
                    "反应体系构建": "192.168.31.205"
                },
                "plc": {"host": "192.168.31.29", "port": 9088},
                "backend": {"host": "127.0.0.1", "port": 8088}
            })
        
        return Response(active_config.config_data)
    
    @action(detail=True, methods=['post'])
    def apply_config(self, request, device_id=None):
        """
        应用新配置（立即生效）
        POST /api/devices/{device_id}/apply_config/
        Body: {config_data}
        """
        from .serializers import DeviceConfigHistorySerializer
        device = self.get_object()
        config_data = request.data
        
        # 验证配置格式
        if not self._validate_config(config_data):
            return Response(
                {'error': '配置格式错误'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 清洗配置数据，移除非法字符
        config_data = self._sanitize_config(config_data)
        
        # 创建配置历史记录
        from .models import DeviceConfigHistory
        config_history = DeviceConfigHistory.objects.create(
            device=device,
            config_data=config_data,
            applied_by=request.user.username,
            status='pending'
        )
        
        # 标记为待应用
        if not device.config:
            device.config = {}
        device.config['pending_config_id'] = config_history.id
        device.save()
        
        return Response({
            'message': '配置已提交，等待设备应用',
            'config_id': config_history.id
        })
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def pending_config(self, request, device_id=None):
        """
        Agent查询待应用的配置
        GET /api/devices/{device_id}/pending_config/
        """
        device = self.get_object()
        pending_id = device.config.get('pending_config_id') if device.config else None
        
        if not pending_id:
            return Response({'has_pending': False})
        
        from .models import DeviceConfigHistory
        try:
            config = DeviceConfigHistory.objects.get(id=pending_id)
            return Response({
                'has_pending': True,
                'config_id': config.id,
                'config_data': config.config_data
            })
        except DeviceConfigHistory.DoesNotExist:
            return Response({'has_pending': False})
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def config_result(self, request, device_id=None):
        """
        Agent上报配置应用结果
        POST /api/devices/{device_id}/config_result/
        Body: {config_id, success, error}
        """
        device = self.get_object()
        config_id = request.data['config_id']
        success = request.data['success']
        
        from .models import DeviceConfigHistory
        config = DeviceConfigHistory.objects.get(id=config_id)
        
        if success:
            # 取消之前的active标记
            device.config_history.update(is_active=False)
            config.status = 'success'
            config.is_active = True
        else:
            config.status = 'failed'
            config.error_message = request.data.get('error', '')
        
        config.save()
        
        # 清除pending标记
        if device.config:
            device.config.pop('pending_config_id', None)
            device.save()
        
        return Response({'message': '已记录'})
    
    @action(detail=True, methods=['get'])
    def config_history(self, request, device_id=None):
        """
        获取配置历史
        GET /api/devices/{device_id}/config_history/
        """
        from .serializers import DeviceConfigHistorySerializer
        device = self.get_object()
        history = device.config_history.all()[:20]  # 最近20条
        serializer = DeviceConfigHistorySerializer(history, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def rollback_config(self, request, device_id=None):
        """
        回滚到历史配置
        POST /api/devices/{device_id}/rollback_config/
        Body: {config_id}
        """
        device = self.get_object()
        config_id = request.data.get('config_id')
        
        from .models import DeviceConfigHistory
        try:
            old_config = DeviceConfigHistory.objects.get(id=config_id, device=device)
            
            # 创建新的配置记录（基于旧配置）
            new_config = DeviceConfigHistory.objects.create(
                device=device,
                config_data=old_config.config_data,
                applied_by=request.user.username,
                status='pending'
            )
            
            # 标记为待应用
            if not device.config:
                device.config = {}
            device.config['pending_config_id'] = new_config.id
            device.save()
            
            return Response({
                'message': '配置回滚已提交',
                'config_id': new_config.id
            })
        except DeviceConfigHistory.DoesNotExist:
            return Response(
                {'error': '配置不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    def _validate_config(self, config_data):
        """验证配置数据"""
        required_keys = ['cameras', 'plc', 'backend']
        if not all(k in config_data for k in required_keys):
            return False
        
        # 验证IP格式
        import ipaddress
        try:
            for ip in config_data['cameras'].values():
                ipaddress.ip_address(ip)
            ipaddress.ip_address(config_data['plc']['host'])
            ipaddress.ip_address(config_data['backend']['host'])
        except:
            return False
        
        return True
    
    def _sanitize_config(self, config_data):
        """清洗配置数据，移除非法字符"""
        import re
        
        def clean_string(s):
            if not isinstance(s, str):
                return s
            # 只保留可打印的ASCII字符、中文字符和基本标点
            # 移除控制字符（0x00-0x1F, 0x7F-0x9F）
            return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', s)
        
        def clean_dict(d):
            if isinstance(d, dict):
                return {clean_string(k): clean_dict(v) for k, v in d.items()}
            elif isinstance(d, list):
                return [clean_dict(item) for item in d]
            elif isinstance(d, str):
                return clean_string(d)
            else:
                return d
        
        return clean_dict(config_data)
    
    # ==================== 日志管理辅助方法 ====================
    def _create_log_task(self, device, task_type, params):
        """
        创建日志任务（无需数据库迁移）
        存储在 Device.config['log_tasks'] 中
        """
        import time
        from datetime import timedelta
        
        # 确保 config 存在
        if not device.config:
            device.config = {}
        if 'log_tasks' not in device.config:
            device.config['log_tasks'] = {}
        
        # 生成任务ID（时间戳）
        task_id = str(int(time.time() * 1000))
        
        # 创建任务
        device.config['log_tasks'][task_id] = {
            'task_type': task_type,
            'params': params,
            'status': 'pending',
            'result': {},
            'error_message': '',
            'created_at': timezone.now().isoformat(),
            'completed_at': None
        }
        
        # 清理7天前的已完成任务
        seven_days_ago = timezone.now() - timedelta(days=7)
        to_delete = []
        for tid, task in device.config['log_tasks'].items():
            if task['status'] in ['completed', 'failed']:
                try:
                    created_at = timezone.datetime.fromisoformat(task['created_at'])
                    if created_at < seven_days_ago:
                        to_delete.append(tid)
                except:
                    pass
        
        for tid in to_delete:
            del device.config['log_tasks'][tid]
        
        device.save()
        
        return task_id
    
    def _get_log_task(self, device, task_id):
        """获取日志任务"""
        if not device.config or 'log_tasks' not in device.config:
            return None
        return device.config['log_tasks'].get(str(task_id))
    
    def _update_log_task(self, device, task_id, task_status, result=None, error_message=''):
        """更新日志任务状态"""
        if not device.config or 'log_tasks' not in device.config:
            return False
        
        task_id_str = str(task_id)
        if task_id_str not in device.config['log_tasks']:
            return False
        
        device.config['log_tasks'][task_id_str]['status'] = task_status
        if result is not None:
            device.config['log_tasks'][task_id_str]['result'] = result
        if error_message:
            device.config['log_tasks'][task_id_str]['error_message'] = error_message
        if task_status in ['completed', 'failed']:
            device.config['log_tasks'][task_id_str]['completed_at'] = timezone.now().isoformat()
        
        device.save()
        return True
    
    # ==================== 日志管理 API ====================
    @action(detail=True, methods=['post'])
    def list_logs(self, request, device_id=None):
        """
        列出设备日志文件
        POST /api/devices/{device_id}/list_logs/
        Body: {"date": "2025-12-10"}  # 可选
        """
        device = self.get_object()
        date = request.data.get('date')
        
        task_id = self._create_log_task(device, 'list', {'date': date} if date else {})
        
        return Response({
            'task_id': task_id,
            'message': '日志列表任务已创建'
        })
    
    @action(detail=True, methods=['post'])
    def read_log(self, request, device_id=None):
        """
        读取日志文件内容
        POST /api/devices/{device_id}/read_log/
        Body: {"date": "2025-12-10", "file": "14h48m.log", "lines": 500, "tail": true}
        """
        device = self.get_object()
        date = request.data.get('date')
        file = request.data.get('file')
        lines = request.data.get('lines', 0)
        tail = request.data.get('tail', False)
        
        if not date or not file:
            return Response({'error': 'date和file参数必填'}, status=status.HTTP_400_BAD_REQUEST)
        
        task_id = self._create_log_task(device, 'read', {
            'date': date,
            'file': file,
            'lines': lines,
            'tail': tail
        })
        
        return Response({'task_id': task_id, 'message': '日志读取任务已创建'})
    
    @action(detail=True, methods=['post'])
    def search_logs(self, request, device_id=None):
        """
        搜索日志内容
        POST /api/devices/{device_id}/search_logs/
        Body: {"keyword": "ERROR", "start_date": "2025-12-01", "end_date": "2025-12-10", "level": "ERROR"}
        """
        device = self.get_object()
        keyword = request.data.get('keyword')
        
        if not keyword:
            return Response({'error': 'keyword参数必填'}, status=status.HTTP_400_BAD_REQUEST)
        
        task_id = self._create_log_task(device, 'search', {
            'keyword': keyword,
            'start_date': request.data.get('start_date'),
            'end_date': request.data.get('end_date'),
            'level': request.data.get('level'),
            'case_sensitive': request.data.get('case_sensitive', False)
        })
        
        return Response({'task_id': task_id, 'message': '日志搜索任务已创建'})
    
    @action(detail=True, methods=['get'])
    def log_task_result(self, request, device_id=None):
        """
        查询日志任务结果
        GET /api/devices/{device_id}/log_task_result/?task_id=1702345678123
        """
        device = self.get_object()
        task_id = request.query_params.get('task_id')
        
        if not task_id:
            return Response({'error': 'task_id参数必填'}, status=status.HTTP_400_BAD_REQUEST)
        
        task = self._get_log_task(device, task_id)
        
        if not task:
            return Response({'error': '任务不存在'}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            'task_id': task_id,
            'task_type': task['task_type'],
            'status': task['status'],
            'result': task['result'],
            'error_message': task['error_message'],
            'created_at': task['created_at'],
            'completed_at': task['completed_at']
        })
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def pending_log_tasks(self, request, device_id=None):
        """
        Agent轮询待执行的日志任务
        GET /api/devices/{device_id}/pending_log_tasks/
        """
        device = self.get_object()
        
        if not device.config or 'log_tasks' not in device.config:
            return Response({'tasks': []})
        
        # 获取所有pending状态的任务
        pending_tasks = []
        for task_id, task in device.config['log_tasks'].items():
            if task['status'] == 'pending':
                pending_tasks.append({
                    'task_id': task_id,
                    'task_type': task['task_type'],
                    'params': task['params']
                })
                # 标记为processing
                device.config['log_tasks'][task_id]['status'] = 'processing'
        
        if pending_tasks:
            device.save()
        
        return Response({'tasks': pending_tasks[:5]})  # 最多返回5个
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def report_log_task(self, request, device_id=None):
        """
        Agent上报日志任务执行结果
        POST /api/devices/{device_id}/report_log_task/
        Body: {"task_id": "1702345678123", "status": "completed", "result": {...}, "error_message": ""}
        """
        device = self.get_object()
        task_id = request.data.get('task_id')
        task_status = request.data.get('status')
        result = request.data.get('result', {})
        error_message = request.data.get('error_message', '')
        
        success = self._update_log_task(device, task_id, task_status, result, error_message)
        
        if success:
            return Response({'message': '任务结果已更新'})
        else:
            return Response({'error': '任务不存在'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def download_log(self, request, device_id=None):
        """
        下载日志文件
        POST /api/devices/{device_id}/download_log/
        Body: {"date": "2025-12-10", "files": ["14h48m.log", "15h20m.log"]}
        """
        device = self.get_object()
        date = request.data.get('date')
        files = request.data.get('files', [])
        
        if not date or not files:
            return Response({'error': 'date和files参数必填'}, status=status.HTTP_400_BAD_REQUEST)
        
        task_id = self._create_log_task(device, 'download', {'date': date, 'files': files})

        return Response({'task_id': task_id, 'message': '日志下载任务已创建'})

    # ==================== FRP 管理 API ====================

    @action(detail=True, methods=['post'])
    def set_frp_enabled(self, request, device_id=None):
        """
        设置设备是否启用 FRP
        POST /api/devices/{device_id}/set_frp_enabled/
        Body: {"enabled": true}
        """
        device = self.get_object()
        enabled = request.data.get('enabled')

        if enabled is None:
            return Response({'error': 'enabled参数必填'}, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(enabled, bool):
            pass
        elif isinstance(enabled, str):
            normalized = enabled.strip().lower()
            if normalized in {'true', '1', 'yes', 'on'}:
                enabled = True
            elif normalized in {'false', '0', 'no', 'off'}:
                enabled = False
            else:
                return Response({'error': 'enabled参数格式错误'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            enabled = bool(enabled)

        frp_cfg = get_frp_config()

        if enabled and not device.frp_enabled:
            device.frp_enabled = True
            device.save(update_fields=['frp_enabled'])

            if frp_cfg.is_active:
                port = allocate_frp_ssh_port(device, frp_config=frp_cfg)
                if not port:
                    device.frp_enabled = False
                    device.save(update_fields=['frp_enabled'])
                    return Response({'error': '端口池已耗尽，无法启用该设备的 FRP'}, status=status.HTTP_400_BAD_REQUEST)

                return Response({
                    'message': '设备 FRP 已启用',
                    'frp_enabled': True,
                    'ssh_port': port,
                    'ssh_command': device.ssh_connection_string,
                })

            return Response({
                'message': '设备 FRP 已启用，待平台侧 FRP 服务启用后会自动分配并下发配置',
                'frp_enabled': True,
                'ssh_port': device.frp_ssh_port,
                'ssh_command': device.ssh_connection_string,
            })

        if not enabled and device.frp_enabled:
            device.frp_enabled = False
            release_device_frp_ports(device, save=False)
            device.save(update_fields=['frp_enabled', 'frp_ssh_port', 'frp_web_port', 'frp_status', 'frp_error_message'])
            mark_device_pending_agent_update(device)

            return Response({
                'message': '设备 FRP 已禁用，在线设备会在下次心跳时停用本地 frpc',
                'frp_enabled': False,
            })

        return Response({
            'message': '设备 FRP 状态未变化',
            'frp_enabled': device.frp_enabled,
            'ssh_port': device.frp_ssh_port,
            'ssh_command': device.ssh_connection_string,
        })

    @action(detail=True, methods=['post'])
    def allocate_frp_ports(self, request, device_id=None):
        """
        为设备分配 FRP 端口（手动触发）
        POST /api/devices/{device_id}/allocate_frp_ports/
        """
        device = self.get_object()

        if not device.frp_enabled:
            return Response({'error': '该设备已禁用 FRP，请先启用后再分配端口'}, status=status.HTTP_400_BAD_REQUEST)

        frp_cfg = get_frp_config()

        # 检查是否已分配
        if device.frp_ssh_port and frp_cfg.port_pool_start <= device.frp_ssh_port <= frp_cfg.port_pool_end:
            return Response({
                'message': '设备已分配端口',
                'ssh_port': device.frp_ssh_port,
                'ssh_command': device.ssh_connection_string or f"ssh -p {device.frp_ssh_port} jetson@{frp_cfg.server_addr}"
            })

        # 分配端口
        port = allocate_frp_ssh_port(device, frp_config=frp_cfg)
        if not port:
            return Response({'error': '端口池已耗尽或 FRP 未启用'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': '端口分配成功',
            'ssh_port': port,
            'ssh_command': device.ssh_connection_string or f"ssh -p {port} jetson@{frp_cfg.server_addr}"
        })

    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def fetch_frp_config(self, request, device_id=None):
        """
        Agent 获取 FRP 配置（数据库为准）
        GET /api/devices/{device_id}/fetch_frp_config/
        """
        device = self.get_object()

        frp_config = build_frp_config_for_device(device, get_frp_config())
        if not frp_config:
            return Response({
                'has_config': False,
                'disable_required': should_disable_frp_for_device(device),
            })
        
        return Response({
            'has_config': True,
            **frp_config
        })

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def report_frp_status(self, request, device_id=None):
        """
        Agent 上报 FRP 状态
        POST /api/devices/{device_id}/report_frp_status/
        Body: {"status": "connected/disconnected/error", "error_message": ""}
        """
        device = self.get_object()

        frp_status = request.data.get('status')
        error_message = request.data.get('error_message', '')

        if should_disable_frp_for_device(device):
            device.frp_status = 'disconnected'
            device.frp_error_message = ''
        else:
            device.frp_status = frp_status
            device.frp_error_message = error_message
        device.frp_last_check = timezone.now()
        device.save()

        return Response({'message': 'ok'})

    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def pending_system_tasks(self, request, device_id=None):
        """
        Agent 轮询待执行的系统配置任务
        GET /api/devices/{device_id}/pending_system_tasks/
        """
        device = self.get_object()

        if not device.config or 'system_tasks' not in device.config:
            return Response({'tasks': []})

        pending = []
        for task_id, task in device.config['system_tasks'].items():
            if task['status'] == 'pending':
                pending.append({'task_id': task_id, **task})
                device.config['system_tasks'][task_id]['status'] = 'processing'

        if pending:
            device.save()

        return Response({'tasks': pending})

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def report_system_task(self, request, device_id=None):
        """
        Agent 上报系统任务执行结果
        POST /api/devices/{device_id}/report_system_task/
        Body: {"task_id": "xxx", "status": "completed/failed", "error_message": ""}
        """
        device = self.get_object()

        task_id = request.data.get('task_id')
        task_status = request.data.get('status')
        error_message = request.data.get('error_message', '')

        if device.config and 'system_tasks' in device.config:
            if task_id in device.config['system_tasks']:
                device.config['system_tasks'][task_id]['status'] = task_status
                device.config['system_tasks'][task_id]['error_message'] = error_message
                device.save()

        return Response({'message': 'ok'})

    @action(detail=True, methods=['post'])
    def setup_factory_config(self, request, device_id=None):
        """
        执行出厂配置
        POST /api/devices/{device_id}/setup_factory_config/
        """
        device = self.get_object()

        # 创建系统任务
        if not device.config:
            device.config = {}
        if 'system_tasks' not in device.config:
            device.config['system_tasks'] = {}

        import time
        task_id = str(int(time.time() * 1000))

        device.config['system_tasks'][task_id] = {
            'task_type': 'setup_factory_config',
            'params': {},
            'status': 'pending',
            'created_at': timezone.now().isoformat()
        }
        device.save()

        return Response({'message': '出厂配置任务已创建', 'task_id': task_id})

    def _push_frp_config_to_device(self, device):
        """推送 FRP 配置到设备（通过 system_tasks）"""
        if not device.config:
            device.config = {}
        if 'system_tasks' not in device.config:
            device.config['system_tasks'] = {}

        import time
        task_id = str(int(time.time() * 1000))

        device.config['system_tasks'][task_id] = {
            'task_type': 'setup_frp',
            'params': {},
            'status': 'pending',
            'created_at': timezone.now().isoformat()
        }
        device.save()


class FrpManagementViewSet(viewsets.ViewSet):
    """FRP 全局管理 API。"""
    permission_classes = [IsAuthenticated]

    def _build_overview(self):
        frp_config = get_frp_config()
        config_data = FrpServerConfigSerializer(frp_config).data
        service = get_frps_service_snapshot()
        devices = FrpDeviceSerializer(
            Device.objects.order_by('created_at', 'id'),
            many=True
        ).data
        return {
            'config': config_data,
            'service': service,
            'devices': devices,
        }

    def list(self, request):
        """获取 FRP 配置总览。"""
        return Response(self._build_overview())

    @action(detail=False, methods=['patch'], url_path='config')
    def update_config(self, request):
        """更新 FRP 配置并同步到 FRP 服务。"""
        frp_config = get_frp_config()
        serializer = FrpServerConfigSerializer(frp_config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        candidate = {
            'server_addr': validated_data.get('server_addr', frp_config.server_addr),
            'server_port': validated_data.get('server_port', frp_config.server_port),
            'token': validated_data.get('token', frp_config.token),
            'port_pool_start': validated_data.get('port_pool_start', frp_config.port_pool_start),
            'port_pool_end': validated_data.get('port_pool_end', frp_config.port_pool_end),
            'is_active': validated_data.get('is_active', frp_config.is_active),
            'description': validated_data.get('description', frp_config.description),
        }
        validate_frp_range(candidate['port_pool_start'], candidate['port_pool_end'])

        old_config_state = {
            'server_addr': frp_config.server_addr,
            'server_port': frp_config.server_port,
            'token': frp_config.token,
            'port_pool_start': frp_config.port_pool_start,
            'port_pool_end': frp_config.port_pool_end,
            'is_active': frp_config.is_active,
            'config_version': frp_config.config_version,
            'description': frp_config.description,
        }
        old_device_state = {
            device.pk: {
                'frp_ssh_port': device.frp_ssh_port,
                'frp_web_port': device.frp_web_port,
                'frp_status': device.frp_status,
                'frp_error_message': device.frp_error_message,
                'config': json.loads(json.dumps(device.config or {})),
            }
            for device in Device.objects.all()
        }

        for field, value in candidate.items():
            setattr(frp_config, field, value)

        assignments = plan_frp_port_assignments(frp_config)

        config_changed = any(candidate[key] != old_config_state[key] for key in candidate)
        if config_changed:
            frp_config.config_version = old_config_state['config_version'] + 1

        try:
            with transaction.atomic():
                frp_config.save()
                apply_frp_port_assignments(frp_config, assignments=assignments)
                if not frp_config.is_active:
                    for device in Device.objects.filter(frp_enabled=True):
                        mark_device_pending_agent_update(device)

            sync_result = sync_frps_service_config(frp_config, restart_if_running=True)
        except Exception as exc:
            with transaction.atomic():
                for field, value in old_config_state.items():
                    setattr(frp_config, field, value)
                frp_config.save()

                for device in Device.objects.all():
                    original = old_device_state[device.pk]
                    device.frp_ssh_port = original['frp_ssh_port']
                    device.frp_web_port = original['frp_web_port']
                    device.frp_status = original['frp_status']
                    device.frp_error_message = original['frp_error_message']
                    device.config = original['config']
                    device.save(update_fields=['frp_ssh_port', 'frp_web_port', 'frp_status', 'frp_error_message', 'config'])

            raise ValidationError({'error': f'FRP 配置保存失败: {exc}'})

        return Response({
            'message': 'FRP 配置已保存并同步到服务',
            'backup_path': sync_result['backup_path'],
            **self._build_overview(),
        })

    @action(detail=False, methods=['post'], url_path='sync')
    def sync(self, request):
        """将数据库中的 FRP 配置重新同步到 FRP 服务。"""
        result = sync_frps_service_config(get_frp_config(), restart_if_running=True)
        return Response({
            'message': 'FRP 配置已重新同步',
            'backup_path': result['backup_path'],
            **self._build_overview(),
        })

    @action(detail=False, methods=['post'], url_path='service')
    def service_control(self, request):
        """控制 FRP 服务容器启停。"""
        action_name = request.data.get('action')
        runtime = get_frp_runtime_settings()

        if action_name not in {'start', 'stop', 'restart'}:
            return Response({'error': 'action 仅支持 start/stop/restart'}, status=status.HTTP_400_BAD_REQUEST)

        if action_name in {'start', 'restart'}:
            sync_frps_service_config(get_frp_config(), restart_if_running=False)

        command = {
            'start': ['start', runtime['container_name']],
            'stop': ['stop', runtime['container_name']],
            'restart': ['restart', runtime['container_name']],
        }[action_name]

        result = run_docker_command(command, check=False, timeout=120)
        if result.returncode != 0:
            return Response(
                {'error': result.stderr.strip() or result.stdout.strip() or 'FRP 服务操作失败'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'message': f'FRP 服务已执行 {action_name}',
            **self._build_overview(),
        })


# ==================== Agent 版本管理 API ====================
@api_view(['GET'])
@permission_classes([AllowAny])
def agent_version(request):
    """
    获取最新 Agent 版本信息
    GET /api/agent/version/
    """
    return Response({
        "version": AGENT_VERSION,
        "download_url": "/api/agent/download/"
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def agent_download(request):
    """
    下载最新 Agent 脚本
    GET /api/agent/download/
    """
    agent_path = os.path.join(settings.BASE_DIR, 'device-agent', 'device-agent.py')
    
    # 如果本地没有，尝试从 device-agent 目录读取
    if not os.path.exists(agent_path):
        # Docker 部署时的路径
        agent_path = '/app/device-agent/device-agent.py'
    
    if os.path.exists(agent_path):
        with open(agent_path, 'r') as f:
            content = f.read()
        return HttpResponse(content, content_type='text/plain')
    else:
        return Response(
            {"error": "Agent script not found"},
            status=status.HTTP_404_NOT_FOUND
        )


class DeploymentTaskViewSet(viewsets.ModelViewSet):
    """部署任务API"""
    queryset = DeploymentTask.objects.all()
    serializer_class = DeploymentTaskSerializer
    
    def get_permissions(self):
        """Agent调用的接口不需要认证"""
        if self.action in ['list', 'retrieve', 'update_progress']:
            return [AllowAny()]
        return super().get_permissions()
    
    def get_queryset(self):
        """支持按设备和状态过滤"""
        queryset = super().get_queryset()
        device = self.request.query_params.get('device')
        status = self.request.query_params.get('status')
        
        if device:
            queryset = queryset.filter(device_id=device)
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def update_progress(self, request, pk=None):
        """更新任务进度（Agent调用，不需要认证）"""
        task = self.get_object()
        
        task.status = request.data.get('status', task.status)
        task.progress = request.data.get('progress', task.progress)
        task.message = request.data.get('message', task.message)
        task.error_message = request.data.get('error_message', task.error_message)
        
        if task.status in ['completed', 'failed']:
            task.completed_at = timezone.now()
        
        task.save()
        
        return Response({"status": "updated"})


class UpdateTaskViewSet(viewsets.ModelViewSet):
    """更新任务API"""
    queryset = UpdateTask.objects.all()
    serializer_class = UpdateTaskSerializer
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def update_progress(self, request, pk=None):
        """更新任务进度（Agent调用，不需要认证）"""
        task = self.get_object()
        
        task.status = request.data.get('status', task.status)
        task.progress = request.data.get('progress', task.progress)
        task.error_message = request.data.get('error_message', task.error_message)
        
        if task.status in ['success', 'failed']:
            task.completed_at = timezone.now()
        
        task.save()
        
        return Response({"status": "updated"})


class DeviceLogViewSet(viewsets.ModelViewSet):
    """设备日志API"""
    queryset = DeviceLog.objects.all()
    serializer_class = DeviceLogSerializer
    
    def get_queryset(self):
        """支持按设备ID过滤"""
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('device_id')
        if device_id:
            queryset = queryset.filter(device__device_id=device_id)
        return queryset


# ==================== 辅助函数 ====================

def load_docker_image(tar_path):
    """
    加载Docker镜像文件（使用Docker CLI）
    
    参数:
        tar_path: .tar文件的绝对路径
    
    返回:
        (image_name, tag, image_id) 或抛出异常
    """
    try:
        if not os.path.exists(tar_path):
            raise Exception(f"文件不存在: {tar_path}")
        
        # 使用docker load命令加载镜像
        result = subprocess.run(
            ['docker', 'load', '-i', tar_path],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        if result.returncode != 0:
            raise Exception(f"Docker load失败: {result.stderr}")
        
        # 解析输出获取镜像信息
        # 输出格式: "Loaded image: name:tag" 或 "Loaded image ID: sha256:..."
        output = result.stdout.strip()
        
        if 'Loaded image:' in output:
            # 提取镜像名称和标签
            image_full = output.split('Loaded image:')[1].strip()
            if ':' in image_full:
                name, tag = image_full.rsplit(':', 1)
            else:
                name = image_full
                tag = 'latest'
        elif 'Loaded image ID:' in output:
            # 只有ID，没有标签
            image_id = output.split('Loaded image ID:')[1].strip()
            # 使用docker inspect获取详细信息
            inspect_result = subprocess.run(
                ['docker', 'inspect', image_id],
                capture_output=True,
                text=True
            )
            if inspect_result.returncode == 0:
                inspect_data = json.loads(inspect_result.stdout)[0]
                tags = inspect_data.get('RepoTags', [])
                if tags and tags[0] != '<none>:<none>':
                    full_tag = tags[0]
                    if ':' in full_tag:
                        name, tag = full_tag.rsplit(':', 1)
                    else:
                        name = full_tag
                        tag = 'latest'
                else:
                    name = 'unnamed'
                    tag = image_id.replace('sha256:', '')[:12]
            else:
                name = 'unnamed'
                tag = image_id.replace('sha256:', '')[:12]
        else:
            raise Exception(f"无法解析docker load输出: {output}")
        
        # 获取镜像ID
        image_id_result = subprocess.run(
            ['docker', 'images', '--format', '{{.ID}}', '--filter', f'reference={name}:{tag}'],
            capture_output=True,
            text=True
        )
        image_id = image_id_result.stdout.strip() if image_id_result.returncode == 0 else 'unknown'
        
        return (name, tag, image_id)
    
    except subprocess.TimeoutExpired:
        raise Exception("加载镜像超时（超过5分钟）")
    except FileNotFoundError:
        raise Exception("Docker命令不存在，请确保Docker已安装并在PATH中")
    except Exception as e:
        raise Exception(f"加载镜像失败: {str(e)}")


def push_to_registry(image_name, tag, registry_url='localhost:5000'):
    """
    推送镜像到Registry（使用Docker CLI）
    
    参数:
        image_name: 镜像名称
        tag: 标签
        registry_url: Registry地址
    
    返回:
        full_name: 完整镜像名称（registry_url/name:tag）
    """
    try:
        # 构建完整名称
        full_name = f"{registry_url}/{image_name}:{tag}"
        
        # 1. 检查原镜像是否存在
        check_result = subprocess.run(
            ['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}', '--filter', f'reference={image_name}:{tag}'],
            capture_output=True,
            text=True
        )
        
        if not check_result.stdout.strip():
            raise Exception(f"镜像不存在: {image_name}:{tag}")
        
        # 2. 打标签
        tag_result = subprocess.run(
            ['docker', 'tag', f'{image_name}:{tag}', full_name],
            capture_output=True,
            text=True
        )
        
        if tag_result.returncode != 0:
            raise Exception(f"打标签失败: {tag_result.stderr}")
        
        # 3. 推送到Registry
        push_result = subprocess.run(
            ['docker', 'push', full_name],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        if push_result.returncode != 0:
            raise Exception(f"推送失败: {push_result.stderr}")
        
        return full_name
    
    except subprocess.TimeoutExpired:
        raise Exception("推送镜像超时（超过5分钟）")
    except FileNotFoundError:
        raise Exception("Docker命令不存在，请确保Docker已安装并在PATH中")
    except Exception as e:
        raise Exception(f"推送镜像失败: {str(e)}")


# ==================== Docker镜像管理ViewSet ====================

class DockerImageViewSet(viewsets.ModelViewSet):
    """Docker镜像管理API"""
    queryset = DockerImage.objects.filter(is_active=True)
    serializer_class = DockerImageSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    @action(detail=False, methods=['post'])
    def upload(self, request):
        """
        上传Docker镜像文件
        POST /api/images/upload/
        
        请求格式: multipart/form-data
        参数:
        - file: .tar文件（必需）
        - name: 镜像名称（可选）
        - tag: 版本标签（可选）
        - description: 描述（可选）
        """
        # 获取上传的文件
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"error": "未提供文件"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证文件扩展名
        if not uploaded_file.name.endswith('.tar'):
            return Response(
                {"error": "只支持.tar格式的镜像文件"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 1. 保存上传的文件
            import datetime
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{uploaded_file.name.rsplit('.', 1)[0]}_{timestamp}.tar"
            
            # 确保目录存在
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'docker_images')
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, filename)
            
            # 写入文件
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            # 获取文件大小
            file_size = os.path.getsize(file_path)
            
            # 2. 加载Docker镜像
            try:
                image_name, image_tag, image_id = load_docker_image(file_path)
            except Exception as e:
                # 加载失败，删除文件
                os.remove(file_path)
                return Response(
                    {"error": f"加载镜像失败: {str(e)}"},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )
            
            # 允许用户覆盖镜像名称和标签
            final_name = request.data.get('name', image_name)
            final_tag = request.data.get('tag', image_tag)
            
            # 3. 推送到Registry
            try:
                registry_url = getattr(settings, 'DOCKER_REGISTRY_URL', 'localhost:5000')
                full_name = push_to_registry(final_name, final_tag, registry_url)
            except Exception as e:
                # 推送失败，删除文件
                os.remove(file_path)
                return Response(
                    {"error": f"推送到Registry失败: {str(e)}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # 4. 保存到数据库
            relative_path = os.path.join('docker_images', filename)
            description = request.data.get('description', '')
            
            # 检查是否已存在相同的镜像
            existing = DockerImage.objects.filter(
                name=final_name,
                tag=final_tag,
                is_active=True
            ).first()
            
            if existing:
                # 更新现有记录
                existing.full_name = full_name
                existing.size = file_size
                existing.file_path = relative_path
                existing.description = description
                existing.save()
                docker_image = existing
            else:
                # 创建新记录
                docker_image = DockerImage.objects.create(
                    name=final_name,
                    tag=final_tag,
                    full_name=full_name,
                    size=file_size,
                    file_path=relative_path,
                    description=description,
                    created_by=request.user.username if request.user.is_authenticated else 'admin'
                )
            
            serializer = self.get_serializer(docker_image)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {"error": f"上传失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def push_to_device(self, request, pk=None):
        """
        推送镜像到指定设备
        POST /api/images/{id}/push_to_device/
        
        请求体:
        {
            "device_ids": ["dev_001", "dev_002"],
            "container_name": "middleware",
            "container_config": {
                "ports": {"8000/tcp": 8000},
                "environment": {"KEY": "value"}
            }
        }
        """
        docker_image = self.get_object()
        device_ids = request.data.get('device_ids', [])
        container_name = request.data.get('container_name', 'middleware')
        container_config = request.data.get('container_config', {})
        
        if not device_ids:
            return Response(
                {"error": "未指定设备"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_tasks = []
        failed_devices = []
        
        for device_id in device_ids:
            try:
                device = Device.objects.get(device_id=device_id)
                
                # 创建部署任务，把镜像信息放在config中
                task = DeploymentTask.objects.create(
                    device=device,
                    target_version=docker_image.tag,
                    status='pending',
                    message=f"等待部署 {docker_image.name}:{docker_image.tag}",
                    config={
                        'image_name': docker_image.name,
                        'image_tag': docker_image.tag,
                        'full_name': docker_image.full_name,
                        'container_name': container_name,
                        'container_config': container_config
                    }
                )
                
                created_tasks.append({
                    'task_id': task.id,
                    'device_id': device_id,
                    'device_name': device.name
                })
                
            except Device.DoesNotExist:
                failed_devices.append({
                    'device_id': device_id,
                    'error': '设备不存在'
                })
        
        return Response({
            "success": len(created_tasks),
            "failed": len(failed_devices),
            "created_tasks": created_tasks,
            "failed_devices": failed_devices
        })
    
    def destroy(self, request, pk=None):
        """
        删除镜像（软删除）
        DELETE /api/images/{id}/
        """
        docker_image = self.get_object()
        
        # 软删除
        docker_image.is_active = False
        docker_image.save()
        
        return Response(
            {"message": "镜像已删除"},
            status=status.HTTP_204_NO_CONTENT
        )


# ==================== 代码包管理ViewSet ====================

class CodePackageViewSet(viewsets.ModelViewSet):
    """代码包管理API"""
    queryset = CodePackage.objects.all()
    serializer_class = CodePackageSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    @action(detail=False, methods=['post'])
    def upload(self, request):
        """
        上传代码包
        POST /api/code-packages/upload/
        
        请求格式: multipart/form-data
        参数:
        - file: .zip 或 .tar.gz 文件
        - name: 包名称
        - version: 版本号
        - description: 更新说明（可选）
        """
        import hashlib
        import datetime
        
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"error": "未提供文件"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证文件格式
        valid_extensions = ['.zip', '.tar.gz', '.tgz']
        is_valid = any(uploaded_file.name.endswith(ext) for ext in valid_extensions)
        if not is_valid:
            return Response(
                {"error": "只支持 .zip, .tar.gz, .tgz 格式的代码包"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        name = request.data.get('name', uploaded_file.name.split('.')[0])
        version = request.data.get('version', 'v1.0.0')
        description = request.data.get('description', '')
        
        try:
            # 保存文件
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            ext = '.tar.gz' if '.tar.gz' in uploaded_file.name or '.tgz' in uploaded_file.name else '.zip'
            filename = f"{name}_{version}_{timestamp}{ext}"
            
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'code_packages')
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, filename)
            
            # 写入文件并计算校验和
            md5_hash = hashlib.md5()
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
                    md5_hash.update(chunk)
            
            file_size = os.path.getsize(file_path)
            checksum = md5_hash.hexdigest()
            
            # 保存到数据库
            code_package = CodePackage.objects.create(
                name=name,
                version=version,
                file_path=os.path.join('code_packages', filename),
                size=file_size,
                checksum=checksum,
                description=description,
                created_by=request.user.username if request.user.is_authenticated else 'admin'
            )
            
            serializer = self.get_serializer(code_package)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {"error": f"上传失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def download(self, request, pk=None):
        """
        下载代码包（Agent调用，不需要认证）
        GET /api/code-packages/{id}/download/
        """
        from django.http import FileResponse
        
        code_package = self.get_object()
        file_path = os.path.join(settings.MEDIA_ROOT, code_package.file_path)
        
        if not os.path.exists(file_path):
            return Response(
                {"error": "文件不存在"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        response = FileResponse(
            open(file_path, 'rb'),
            content_type='application/octet-stream'
        )
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
        return response


# ==================== 安装脚本下载 ====================

@api_view(['GET'])
@permission_classes([AllowAny])
def get_install_script(request):
    """
    提供完整的bash安装脚本
    GET /api/install.sh
    使用方法: curl -fsSL http://your-server:8081/api/install.sh | sudo bash
    """
    # 获取服务器地址（确保包含端口号）
    host = request.get_host()
    if ':' not in host:
        host = f"{host}:8081"
    server_url = f"http://{host}/api"
    
    # 完整的bash安装脚本
    script = f'''#!/bin/bash
#
# 设备管理平台 - 一键安装脚本
# 自动安装Docker、Python依赖和设备Agent
#

set -e

CLOUD_SERVER="{server_url}"
PYTHON_BIN="/usr/bin/python3"

echo "========================================"
echo "设备管理平台 - 一键安装"
echo "========================================"
echo "管理中心: $CLOUD_SERVER"
echo ""

# 1. 安装依赖
echo "[1/4] 安装依赖..."
apt-get update -qq > /dev/null 2>&1
apt-get install -y python3 python3-requests python3-psutil python3-yaml curl
echo "  - Python3 和 Agent 依赖已安装"
if ! "$PYTHON_BIN" -c "import requests, psutil, yaml" >/dev/null 2>&1; then
    echo "  - Python依赖校验失败"
    exit 1
fi
echo "  - Python依赖校验通过"
if ! command -v docker >/dev/null 2>&1; then
    apt-get install -y docker.io
    echo "  - Docker 已安装"
else
    echo "  - Docker 已存在，跳过安装"
fi
systemctl enable docker > /dev/null 2>&1 || true
systemctl start docker > /dev/null 2>&1 || true
echo "  - Docker服务已启动"

# 2. 创建目录
echo "[2/4] 创建工作目录..."
mkdir -p /opt/device-agent
echo "  - 保留现有设备ID（如存在）"

# 3. 下载完整的Agent
echo "[3/4] 下载Agent..."
AGENT_URL="${{CLOUD_SERVER}}/agent/device-agent.py"

if curl -fsSL "$AGENT_URL" -o /opt/device-agent/agent.py 2>/dev/null; then
    echo "  - Agent下载成功 (curl)"
elif wget -q "$AGENT_URL" -O /opt/device-agent/agent.py 2>/dev/null; then
    echo "  - Agent下载成功 (wget)"
else
    echo "  - 下载失败！"
    echo "  - URL: $AGENT_URL"
    echo "  - 请检查网络连接和服务器状态"
    exit 1
fi

# 验证文件
if [ ! -f /opt/device-agent/agent.py ] || [ ! -s /opt/device-agent/agent.py ]; then
    echo "  - Agent文件无效或为空"
    exit 1
fi

FILE_SIZE=$(stat -f%z "/opt/device-agent/agent.py" 2>/dev/null || stat -c%s "/opt/device-agent/agent.py" 2>/dev/null)
echo "  - Agent文件大小: ${{FILE_SIZE}} bytes"

chmod +x /opt/device-agent/agent.py
echo "  - 权限设置完成"

# 4. 创建systemd服务
echo "[4/4] 配置开机自启..."
cat > /etc/systemd/system/device-agent.service <<EOF
[Unit]
Description=Device Management Agent
After=network.target docker.service

[Service]
Type=simple
User=root
Environment="CLOUD_SERVER=$CLOUD_SERVER"
ExecStart=$PYTHON_BIN /opt/device-agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
echo "  - Service文件已创建"

systemctl daemon-reload
echo "  - Systemd已重载"

systemctl stop device-agent > /dev/null 2>&1 || true
systemctl enable device-agent > /dev/null 2>&1
echo "  - 开机自启已启用"

systemctl start device-agent
echo "  - Agent服务已启动"

sleep 2

# 检查服务状态
if systemctl is-active --quiet device-agent; then
    echo ""
    echo "========================================"
    echo "✓ 安装成功！"
    echo "========================================"
    echo ""
    echo "Agent已启动，设备正在连接管理中心..."
    echo "请在管理界面查看设备状态"
    echo ""
    echo "常用命令:"
    echo "  查看日志: sudo journalctl -u device-agent -f"
    echo "  重启服务: sudo systemctl restart device-agent"
    echo "  查看状态: sudo systemctl status device-agent"
    echo ""
else
    echo ""
    echo "========================================"
    echo "! 安装完成但服务启动失败"
    echo "========================================"
    echo ""
    echo "请查看日志排查问题:"
    echo "  sudo journalctl -u device-agent -n 50"
    echo ""
fi
'''
    
    return HttpResponse(script, content_type='text/x-sh; charset=utf-8')


@api_view(['GET'])
@permission_classes([AllowAny])
def get_agent_script(request):
    """
    提供完整的Device Agent脚本下载
    GET /api/agent/device-agent.py
    """
    import os
    from django.conf import settings
    
    # 读取完整的device-agent.py文件
    # 在Docker容器中路径是 /app/device-agent/device-agent.py
    # 在本地开发环境中路径是 ../device-agent/device-agent.py
    possible_paths = [
        os.path.join(settings.BASE_DIR, 'device-agent', 'device-agent.py'),  # Docker: /app/device-agent/
        os.path.join(settings.BASE_DIR, '..', 'device-agent', 'device-agent.py'),  # 本地开发
    ]
    
    agent_path = None
    for path in possible_paths:
        if os.path.exists(path):
            agent_path = path
            break
    
    if not agent_path:
        return Response(
            {"error": "Agent script not found", "searched_paths": possible_paths},
            status=status.HTTP_404_NOT_FOUND
        )
    
    try:
        with open(agent_path, 'r', encoding='utf-8') as f:
            agent_script = f.read()
        
        # 动态替换CLOUD_SERVER地址
        host = request.get_host()
        # 确保包含端口号
        if ':' not in host:
            host = f"{host}:8081"
        server_url = f"http://{host}/api"
        
        # 替换默认的CLOUD_SERVER值
        agent_script = agent_script.replace(
            'CLOUD_SERVER = os.getenv("CLOUD_SERVER", "http://your-server.com/api")',
            f'CLOUD_SERVER = os.getenv("CLOUD_SERVER", "{server_url}")'
        )
        
        return HttpResponse(agent_script, content_type='text/plain')
    except FileNotFoundError:
        return Response(
            {"error": "Agent script not found"},
            status=status.HTTP_404_NOT_FOUND
        )


# ==================== 项目管理 ====================

class ProjectViewSet(viewsets.ModelViewSet):
    """项目管理API"""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    
    @action(detail=True, methods=['post'])
    def deploy_to_devices(self, request, pk=None):
        """
        部署项目到指定设备
        POST /api/projects/{id}/deploy_to_devices/
        Body: {
            "device_ids": ["DEV-001", "DEV-002"]
        }
        """
        project = self.get_object()
        device_ids = request.data.get('device_ids', [])
        
        if not device_ids:
            return Response(
                {"error": "device_ids is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_deployments = []
        failed_devices = []
        
        for device_id in device_ids:
            try:
                device = Device.objects.get(device_id=device_id)
                
                # 创建部署任务
                deployment = ProjectDeployment.objects.create(
                    project=project,
                    device=device,
                    deployed_version=project.version,
                    status='pending',
                    message=f'准备部署项目 {project.name}'
                )
                
                created_deployments.append({
                    'deployment_id': deployment.id,
                    'device_id': device_id
                })
                
            except Device.DoesNotExist:
                failed_devices.append({
                    'device_id': device_id,
                    'error': '设备不存在'
                })
        
        return Response({
            "success": len(created_deployments),
            "failed": len(failed_devices),
            "deployments": created_deployments,
            "failed_devices": failed_devices
        })
    
    @action(detail=True, methods=['post'])
    def set_config(self, request, pk=None):
        """
        设置项目配置
        POST /api/projects/{id}/set_config/
        Body: {
            "configs": [
                {"key": "CAMERA_IP", "value": "192.168.1.100", "description": "相机IP"},
                {"key": "THRESHOLD", "value": "0.85"}
            ]
        }
        """
        project = self.get_object()
        configs = request.data.get('configs', [])
        
        created_count = 0
        updated_count = 0
        
        for config_data in configs:
            key = config_data.get('key')
            value = config_data.get('value')
            
            if not key:
                continue
            
            config, created = ProjectConfig.objects.update_or_create(
                project=project,
                key=key,
                defaults={
                    'value': value,
                    'description': config_data.get('description', ''),
                    'is_secret': config_data.get('is_secret', False)
                }
            )
            
            if created:
                created_count += 1
            else:
                updated_count += 1
        
        return Response({
            "message": "配置已更新",
            "created": created_count,
            "updated": updated_count
        })


class ProjectDeploymentViewSet(viewsets.ModelViewSet):
    """项目部署管理API"""
    queryset = ProjectDeployment.objects.all()
    serializer_class = ProjectDeploymentSerializer
    
    def get_permissions(self):
        """Agent调用的接口不需要认证"""
        if self.action in ['list', 'retrieve', 'update_progress']:
            return [AllowAny()]
        return super().get_permissions()
    
    def get_queryset(self):
        """支持按设备和项目过滤"""
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('device_id')
        project_id = self.request.query_params.get('project_id')
        status = self.request.query_params.get('status')
        
        if device_id:
            queryset = queryset.filter(device__device_id=device_id)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status:
            status_values = [value.strip() for value in status.split(',') if value.strip()]
            if len(status_values) > 1:
                queryset = queryset.filter(status__in=status_values)
            elif status_values:
                queryset = queryset.filter(status=status_values[0])
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def update_progress(self, request, pk=None):
        """
        更新部署进度（Agent调用）
        POST /api/project-deployments/{id}/update_progress/
        Body: {
            "status": "pulling_code",
            "progress": 50,
            "message": "正在拉取代码...",
            "git_commit": "abc123"
        }
        """
        deployment = self.get_object()
        
        deployment.status = request.data.get('status', deployment.status)
        deployment.progress = request.data.get('progress', deployment.progress)
        deployment.message = request.data.get('message', deployment.message)
        deployment.error_message = request.data.get('error_message', deployment.error_message)
        
        if request.data.get('git_commit'):
            deployment.git_commit = request.data['git_commit']
        
        if deployment.status in ['completed', 'failed']:
            deployment.completed_at = timezone.now()
        
        deployment.save()
        
        # 明确返回UTF-8编码的JSON响应，确保所有设备都能正确解析中文
        response = Response({"status": "updated"})
        response['Content-Type'] = 'application/json; charset=utf-8'
        return response


# ==================== 用户认证 ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def user_login(request):
    """
    用户登录
    POST /api/auth/login/
    Body: {
        "username": "admin",
        "password": "password"
    }
    """
    username = request.data.get('username')
    password = request.data.get('password')
    
    if not username or not password:
        return Response(
            {"error": "用户名和密码不能为空"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    user = authenticate(username=username, password=password)
    
    if user is None:
        return Response(
            {"error": "用户名或密码错误"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    if not user.is_active:
        return Response(
            {"error": "用户已被禁用"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # 获取或创建 Token
    token, created = Token.objects.get_or_create(user=user)
    
    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_logout(request):
    """
    用户登出
    POST /api/auth/logout/
    """
    try:
        request.user.auth_token.delete()
    except:
        pass
    
    return Response({"message": "已登出"})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_info(request):
    """
    获取当前用户信息
    GET /api/auth/user/
    """
    user = request.user
    return Response({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser
    })
