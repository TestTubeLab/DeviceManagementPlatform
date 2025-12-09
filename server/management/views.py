"""
设备管理API视图
"""
import os
import subprocess
import json
from django.conf import settings
from django.utils import timezone
from django.http import HttpResponse
from django.contrib.auth import authenticate
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from .models import (
    Device, DeploymentTask, UpdateTask, DeviceLog, DockerImage,
    CodePackage, Project, ProjectConfig, ProjectDeployment
)
from .serializers import (
    DeviceSerializer, DeploymentTaskSerializer,
    UpdateTaskSerializer, DeviceLogSerializer, DockerImageSerializer,
    CodePackageSerializer, ProjectSerializer, ProjectConfigSerializer, ProjectDeploymentSerializer
)

# Agent 最新版本号（每次更新 Agent 时需要同步修改）
AGENT_VERSION = "1.1.0"


class DeviceViewSet(viewsets.ModelViewSet):
    """设备管理API"""
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = 'device_id'
    
    def get_permissions(self):
        """Agent 调用的接口不需要认证"""
        if self.action in ['register', 'heartbeat', 'retrieve', 'list', 'upload_logs', 'pending_config', 'config_result']:
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
        device_id = request.data.get('device_id')
        mac_address = request.data.get('mac_address')
        ip_address = request.data.get('ip_address')
        
        if not device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 获取或创建设备
        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={
                'mac_address': mac_address,
                'ip_address': ip_address,
                'status': 'waiting',
            }
        )
        
        if not created:
            # 更新现有设备信息
            device.mac_address = mac_address
            device.ip_address = ip_address
            device.last_heartbeat = timezone.now()
            device.save()
        
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
            "auto_deploy_project": device.auto_deploy_project.name if device.auto_deploy_project else None
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
            
            # 存储新日志
            for line in lines:
                if line.strip():
                    # 简单判断日志级别
                    level = 'INFO'
                    if '[ERROR]' in line or 'ERROR' in line:
                        level = 'ERROR'
                    elif '[WARNING]' in line or 'WARNING' in line:
                        level = 'WARNING'
                    elif '[DEBUG]' in line:
                        level = 'DEBUG'
                    
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

echo "========================================"
echo "设备管理平台 - 一键安装"
echo "========================================"
echo "管理中心: $CLOUD_SERVER"
echo ""

# 1. 安装依赖
echo "[1/4] 安装依赖..."
apt-get update -qq > /dev/null 2>&1
apt-get install -y python3 python3-pip docker.io curl 2>&1 | grep -v "^W:" || true
echo "  - Python3和Docker已安装"
pip3 install -q requests psutil 2>&1 | grep -v "Requirement already satisfied" || true
echo "  - Python依赖已安装"
systemctl enable docker > /dev/null 2>&1 || true
systemctl start docker > /dev/null 2>&1 || true
echo "  - Docker服务已启动"

# 2. 创建目录并清理旧设备ID
echo "[2/4] 创建工作目录..."
mkdir -p /opt/device-agent

# 清理旧的设备ID，强制重新注册
# 这样可以避免设备被删除后无法重新上线的问题
if [ -f /etc/device-id ]; then
    echo "  - 发现旧设备ID，清理中..."
    rm -f /etc/device-id
    echo "  - 设备将重新注册"
fi

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
ExecStart=/usr/bin/python3 /opt/device-agent/agent.py
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
            queryset = queryset.filter(status=status)
        
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
        
        return Response({"status": "updated"})


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
