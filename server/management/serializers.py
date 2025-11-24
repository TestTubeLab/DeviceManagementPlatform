"""
序列化器
"""
from rest_framework import serializers
from .models import Device, DeploymentTask, UpdateTask, DeviceLog


class DeviceSerializer(serializers.ModelSerializer):
    """设备序列化器"""
    is_online = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Device
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'last_heartbeat']


class DeploymentTaskSerializer(serializers.ModelSerializer):
    """部署任务序列化器"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = DeploymentTask
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'completed_at']


class UpdateTaskSerializer(serializers.ModelSerializer):
    """更新任务序列化器"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = UpdateTask
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'completed_at']


class DeviceLogSerializer(serializers.ModelSerializer):
    """设备日志序列化器"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = DeviceLog
        fields = '__all__'
        read_only_fields = ['timestamp']

