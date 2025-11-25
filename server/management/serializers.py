"""
序列化器
"""
from rest_framework import serializers
from .models import (
    Device, DeploymentTask, UpdateTask, DeviceLog, DockerImage,
    CodePackage, Project, ProjectConfig, ProjectDeployment
)


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


class DockerImageSerializer(serializers.ModelSerializer):
    """Docker镜像序列化器"""
    
    # 只读字段（自动计算）
    size_mb = serializers.SerializerMethodField()
    
    class Meta:
        model = DockerImage
        fields = [
            'id', 'name', 'tag', 'full_name', 'size', 'size_mb',
            'file_path', 'description', 'created_by', 'is_active',
            'uploaded_at'
        ]
        read_only_fields = ['id', 'full_name', 'file_path', 'uploaded_at', 'size']
    
    def get_size_mb(self, obj):
        """将字节转换为MB显示"""
        return round(obj.size / (1024 * 1024), 2)


class CodePackageSerializer(serializers.ModelSerializer):
    """代码包序列化器"""
    
    size_mb = serializers.SerializerMethodField()
    
    class Meta:
        model = CodePackage
        fields = [
            'id', 'name', 'version', 'file_path', 'size', 'size_mb',
            'checksum', 'description', 'created_by', 'uploaded_at'
        ]
        read_only_fields = ['id', 'file_path', 'size', 'checksum', 'uploaded_at']
    
    def get_size_mb(self, obj):
        return round(obj.size / (1024 * 1024), 2)


class ProjectConfigSerializer(serializers.ModelSerializer):
    """项目配置序列化器"""
    
    class Meta:
        model = ProjectConfig
        fields = '__all__'


class ProjectSerializer(serializers.ModelSerializer):
    """项目序列化器"""
    configs = ProjectConfigSerializer(many=True, read_only=True)
    docker_image_info = serializers.SerializerMethodField()
    code_package_info = serializers.SerializerMethodField()
    deployed_devices_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']
    
    def get_docker_image_info(self, obj):
        """获取Docker镜像信息"""
        if obj.docker_image:
            return {
                'id': obj.docker_image.id,
                'name': obj.docker_image.name,
                'tag': obj.docker_image.tag,
                'full_name': obj.docker_image.full_name
            }
        return None
    
    def get_code_package_info(self, obj):
        """获取代码包信息"""
        if obj.code_package:
            return {
                'id': obj.code_package.id,
                'name': obj.code_package.name,
                'version': obj.code_package.version,
                'size_mb': round(obj.code_package.size / (1024 * 1024), 2)
            }
        return None
    
    def get_deployed_devices_count(self, obj):
        """获取已部署设备数量"""
        return Device.objects.filter(auto_deploy_project=obj).count()


class ProjectDeploymentSerializer(serializers.ModelSerializer):
    """项目部署序列化器"""
    project_name = serializers.CharField(source='project.name', read_only=True)
    device_name = serializers.CharField(source='device.device_id', read_only=True)
    
    class Meta:
        model = ProjectDeployment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'completed_at', 'git_commit']

