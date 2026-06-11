"""
序列化器
"""
from rest_framework import serializers
from .models import (
    Device, DeploymentTask, UpdateTask, DeviceLog, DockerImage,
    CodePackage, Project, ProjectConfig, ProjectDeployment, DeviceConfigHistory,
    FrpServerConfig
)


class DeviceSerializer(serializers.ModelSerializer):
    """设备序列化器"""
    is_online = serializers.SerializerMethodField()
    computed_status = serializers.SerializerMethodField()
    computed_service_status = serializers.SerializerMethodField()
    agent_version = serializers.SerializerMethodField()
    ssh_connection_string = serializers.SerializerMethodField()
    web_access_url = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'last_heartbeat', 'hardware_fingerprint']

    def get_is_online(self, obj):
        """动态计算是否在线（2分钟内有心跳）"""
        return obj.is_online

    def get_computed_status(self, obj):
        """动态计算设备状态"""
        return obj.computed_status

    def get_computed_service_status(self, obj):
        """动态计算服务状态"""
        return obj.computed_service_status

    def get_agent_version(self, obj):
        """获取 Agent 版本（存储在 config 字段中）"""
        if obj.config:
            return obj.config.get('agent_version', 'unknown')
        return 'unknown'

    def get_ssh_connection_string(self, obj):
        """获取 SSH 连接字符串"""
        return obj.ssh_connection_string

    def get_web_access_url(self, obj):
        """获取 Web 访问 URL"""
        return obj.web_access_url


class FrpDeviceSerializer(serializers.ModelSerializer):
    """FRP 管理页设备精简序列化器"""
    computed_status = serializers.SerializerMethodField()
    agent_version = serializers.SerializerMethodField()
    ssh_connection_string = serializers.SerializerMethodField()
    web_access_url = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            'id', 'device_id', 'name', 'ip_address',
            'status', 'computed_status', 'last_heartbeat', 'agent_version',
            'frp_enabled', 'frp_ssh_port', 'frp_web_port', 'frp_status',
            'ssh_connection_string', 'web_access_url',
        ]

    def get_computed_status(self, obj):
        return obj.computed_status

    def get_agent_version(self, obj):
        if obj.config:
            return obj.config.get('agent_version', 'unknown')
        return 'unknown'

    def get_ssh_connection_string(self, obj):
        return obj.ssh_connection_string

    def get_web_access_url(self, obj):
        return obj.web_access_url


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
        return (
            ProjectDeployment.objects
            .filter(project=obj, task_type='deploy')
            .exclude(status='failed')
            .values('device_id')
            .distinct()
            .count()
        )


class ProjectDeploymentSerializer(serializers.ModelSerializer):
    """项目部署序列化器"""
    project_name = serializers.SerializerMethodField()
    device_name = serializers.CharField(source='device.device_id', read_only=True)
    # 完整项目信息（供Agent使用）
    project_info = serializers.SerializerMethodField()
    # 设备信息（供前端显示）
    device_info = serializers.SerializerMethodField()
    
    def get_project_name(self, obj):
        """返回项目名称，处理 null 情况"""
        if obj.project:
            return obj.project.name
        return None
    
    class Meta:
        model = ProjectDeployment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'completed_at', 'git_commit']
    
    def get_device_info(self, obj):
        """返回设备基本信息"""
        device = obj.device
        return {
            'id': device.id,
            'device_id': device.device_id,
            'name': device.name or device.device_id,
            'ip_address': device.ip_address,
            'status': device.status
        }
    
    def get_project_info(self, obj):
        """返回完整的项目信息，包括镜像、代码包、配置等"""
        project = obj.project
        
        # 如果没有关联项目（如重启任务），返回 None
        if not project:
            return None
        
        # 获取Docker镜像信息
        docker_image_info = None
        if project.docker_image:
            docker_image_info = {
                'id': project.docker_image.id,
                'name': project.docker_image.name,
                'tag': project.docker_image.tag,
                'full_name': project.docker_image.full_name
            }
        
        # 获取代码包信息
        code_package_info = None
        if project.code_package:
            code_package_info = {
                'id': project.code_package.id,
                'name': project.code_package.name,
                'version': project.code_package.version,
                'size': project.code_package.size
            }
        
        # 获取配置
        configs = [
            {'key': c.key, 'value': c.value, 'description': c.description}
            for c in project.configs.all()
        ]
        
        return {
            'id': project.id,
            'name': project.name,
            'version': project.version,
            'description': project.description,
            # Docker镜像相关
            'docker_image_info': docker_image_info,
            'local_image_name': project.local_image_name,  # 本地预装镜像名
            # 代码相关
            'code_package_info': code_package_info,
            'git_repo': project.git_repo,
            'git_branch': project.git_branch,
            'code_mount_path': project.code_mount_path,
            # 容器相关
            'work_dir': project.work_dir,
            'start_command': project.start_command,
            'container_name': project.container_name,
            'container_config': project.container_config,
            # 配置
            'configs': configs
        }


class DeviceConfigHistorySerializer(serializers.ModelSerializer):
    """设备配置历史序列化器"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    device_id = serializers.CharField(source='device.device_id', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DeviceConfigHistory
        fields = [
            'id', 'device', 'device_name', 'device_id',
            'config_data', 'applied_by', 'applied_at',
            'status', 'status_display', 'error_message', 'is_active'
        ]
        read_only_fields = ['id', 'applied_at']


class FrpServerConfigSerializer(serializers.ModelSerializer):
    """FRP 服务器配置序列化器"""
    available_ports = serializers.SerializerMethodField()
    total_ports = serializers.SerializerMethodField()
    used_ports_count = serializers.SerializerMethodField()
    available_ports_count = serializers.SerializerMethodField()
    enabled_devices_count = serializers.SerializerMethodField()
    connected_devices_count = serializers.SerializerMethodField()

    class Meta:
        model = FrpServerConfig
        fields = [
            'id', 'server_addr', 'server_port', 'token',
            'port_pool_start', 'port_pool_end',
            'web_port_pool_start', 'web_port_pool_end', 'web_pool_enabled',
            'is_active', 'config_version',
            'description', 'created_at', 'updated_at', 'available_ports',
            'total_ports', 'used_ports_count', 'available_ports_count',
            'enabled_devices_count', 'connected_devices_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'config_version', 'web_pool_enabled']

    def get_available_ports(self, obj):
        """获取可用端口列表"""
        return obj.available_ports

    def get_total_ports(self, obj):
        return obj.total_ports

    def get_used_ports_count(self, obj):
        return obj.total_ports - len(obj.available_ports)

    def get_available_ports_count(self, obj):
        return len(obj.available_ports)

    def get_enabled_devices_count(self, obj):
        return Device.objects.filter(frp_enabled=True).count()

    def get_connected_devices_count(self, obj):
        return Device.objects.filter(frp_enabled=True, frp_status='connected').count()
