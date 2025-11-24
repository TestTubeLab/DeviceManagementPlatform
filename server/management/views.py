"""
设备管理API视图
"""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Device, DeploymentTask, UpdateTask, DeviceLog
from .serializers import (
    DeviceSerializer, DeploymentTaskSerializer,
    UpdateTaskSerializer, DeviceLogSerializer
)


class DeviceViewSet(viewsets.ModelViewSet):
    """设备管理API"""
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = 'device_id'
    
    @action(detail=False, methods=['post'])
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
        
        return Response({
            "device_id": device.device_id,
            "status": device.status,
            "created": created,
        })
    
    @action(detail=True, methods=['post'])
    def heartbeat(self, request, device_id=None):
        """
        设备心跳接口
        POST /api/devices/{device_id}/heartbeat/
        Body: {
            "version": "v1.0.3",
            "cpu_usage": 45.2,
            "memory_usage": 62.5,
            "disk_usage": 38.7
        }
        """
        device = self.get_object()
        
        # 更新设备状态
        device.current_version = request.data.get('version', device.current_version)
        device.cpu_usage = request.data.get('cpu_usage', 0)
        device.memory_usage = request.data.get('memory_usage', 0)
        device.disk_usage = request.data.get('disk_usage', 0)
        device.last_heartbeat = timezone.now()
        
        # 更新在线状态
        if device.status == 'offline':
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
        
        if pending_deployment:
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
    
    @action(detail=True, methods=['get'])
    def deployment(self, request, device_id=None):
        """
        获取部署指令
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
    
    @action(detail=True, methods=['post'])
    def progress(self, request, device_id=None):
        """
        上报部署/更新进度
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


class DeploymentTaskViewSet(viewsets.ModelViewSet):
    """部署任务API"""
    queryset = DeploymentTask.objects.all()
    serializer_class = DeploymentTaskSerializer
    
    @action(detail=True, methods=['post'])
    def update_progress(self, request, pk=None):
        """更新任务进度"""
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
    
    @action(detail=True, methods=['post'])
    def update_progress(self, request, pk=None):
        """更新任务进度"""
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
