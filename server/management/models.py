"""
设备管理核心数据模型
"""
from django.db import models
from django.utils import timezone


class DockerImage(models.Model):
    """Docker镜像"""
    
    name = models.CharField(max_length=255, verbose_name='镜像名称')
    tag = models.CharField(max_length=100, verbose_name='版本标签')
    full_name = models.CharField(max_length=500, verbose_name='完整名称', unique=True)
    size = models.BigIntegerField(verbose_name='镜像大小(字节)')
    file_path = models.CharField(max_length=1000, verbose_name='本地存储路径')
    description = models.TextField(blank=True, verbose_name='描述')
    created_by = models.CharField(max_length=100, default='admin', verbose_name='上传者')
    is_active = models.BooleanField(default=True, verbose_name='是否可用')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')
    
    class Meta:
        verbose_name = 'Docker镜像'
        verbose_name_plural = 'Docker镜像列表'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.name}:{self.tag}"


class CodePackage(models.Model):
    """代码包 - 用于快速更新代码而不用重新打包镜像"""
    
    name = models.CharField(max_length=255, verbose_name='包名称')
    version = models.CharField(max_length=50, verbose_name='版本')
    file_path = models.CharField(max_length=1000, verbose_name='文件路径')
    size = models.BigIntegerField(verbose_name='文件大小(字节)')
    checksum = models.CharField(max_length=64, blank=True, verbose_name='校验和')
    description = models.TextField(blank=True, verbose_name='更新说明')
    created_by = models.CharField(max_length=100, default='admin', verbose_name='上传者')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')
    
    class Meta:
        verbose_name = '代码包'
        verbose_name_plural = '代码包列表'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.name} ({self.version})"


class Project(models.Model):
    """项目定义"""
    
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('active', '活跃'),
        ('archived', '归档'),
    ]
    
    name = models.CharField(max_length=200, verbose_name='项目名称')
    description = models.TextField(blank=True, verbose_name='项目描述')
    version = models.CharField(max_length=50, verbose_name='当前版本')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='状态')
    
    # Docker镜像（环境）- 从平台上传的镜像
    docker_image = models.ForeignKey(
        DockerImage, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Docker镜像(平台托管)'
    )
    
    # 本地预装镜像名称（如 newserver:latest）- 设备上已有的镜像
    local_image_name = models.CharField(max_length=255, blank=True, verbose_name='本地镜像名称(设备预装)')
    
    # 代码包（可选，用于代码热更新）
    code_package = models.ForeignKey(
        CodePackage, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='代码包'
    )
    
    # 代码挂载路径（宿主机上的代码目录）
    code_mount_path = models.CharField(max_length=500, default='/opt/project-code', verbose_name='代码挂载路径(宿主机)')
    
    git_repo = models.CharField(max_length=500, blank=True, verbose_name='Git仓库地址(备用)')
    git_branch = models.CharField(max_length=100, default='main', verbose_name='Git分支')
    work_dir = models.CharField(max_length=500, default='/work', verbose_name='容器内工作目录')
    start_command = models.TextField(default='/start.sh', verbose_name='启动命令')
    container_name = models.CharField(max_length=255, default='app', verbose_name='容器名称')
    container_config = models.JSONField(default=dict, verbose_name='容器配置')
    
    created_by = models.CharField(max_length=100, default='admin', verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '项目'
        verbose_name_plural = '项目列表'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.version})"


class Device(models.Model):
    """设备信息"""
    
    STATUS_CHOICES = [
        ('waiting', '等待部署'),
        ('deploying', '部署中'),
        ('online', '在线'),
        ('offline', '离线'),
        ('updating', '更新中'),
        ('error', '异常'),
    ]
    
    # 基本信息
    device_id = models.CharField(max_length=100, unique=True, verbose_name='设备ID')
    name = models.CharField(max_length=200, verbose_name='设备名称', blank=True)
    location = models.CharField(max_length=200, verbose_name='安装位置', blank=True)
    mac_address = models.CharField(max_length=17, verbose_name='MAC地址', blank=True)
    ip_address = models.CharField(max_length=50, verbose_name='IP地址', blank=True)
    
    # 状态信息
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting', verbose_name='状态')
    current_version = models.CharField(max_length=50, verbose_name='当前版本', blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳时间')
    
    # 硬件信息
    cpu_usage = models.FloatField(default=0, verbose_name='CPU使用率')
    memory_usage = models.FloatField(default=0, verbose_name='内存使用率')
    disk_usage = models.FloatField(default=0, verbose_name='磁盘使用率')
    
    # 服务监控信息
    CONTAINER_STATUS_CHOICES = [
        ('running', '运行中'),
        ('stopped', '已停止'),
        ('not_found', '未找到'),
        ('error', '异常'),
    ]
    SERVICE_STATUS_CHOICES = [
        ('healthy', '健康'),
        ('unhealthy', '不健康'),
        ('unknown', '未知'),
    ]
    container_status = models.CharField(
        max_length=20, choices=CONTAINER_STATUS_CHOICES, default='not_found', verbose_name='容器状态'
    )
    container_name = models.CharField(max_length=100, blank=True, default='middleware', verbose_name='容器名称')
    container_uptime = models.CharField(max_length=100, blank=True, verbose_name='容器运行时长')
    service_status = models.CharField(
        max_length=20, choices=SERVICE_STATUS_CHOICES, default='unknown', verbose_name='服务状态'
    )
    service_response_time = models.IntegerField(default=0, verbose_name='服务响应时间(ms)')
    health_check_url = models.CharField(
        max_length=200, blank=True, default='http://localhost:8088/api/', verbose_name='健康检查URL'
    )
    last_health_check = models.DateTimeField(null=True, blank=True, verbose_name='最后健康检查时间')
    
    # 配置信息（JSON字段，存储设备特定配置）
    config = models.JSONField(default=dict, verbose_name='设备配置')

    # FRP 隧道配置
    frp_enabled = models.BooleanField(default=True, verbose_name='启用FRP')
    frp_ssh_port = models.IntegerField(null=True, blank=True, help_text="分配的SSH端口")
    frp_web_port = models.IntegerField(null=True, blank=True, help_text="分配的Web端口")
    frp_status = models.CharField(
        max_length=20,
        default='disconnected',
        choices=[
            ('disconnected', '未连接'),
            ('connecting', '连接中'),
            ('connected', '已连接'),
            ('error', '错误')
        ],
        verbose_name='FRP状态'
    )
    frp_last_check = models.DateTimeField(null=True, blank=True, help_text="FRP状态最后检查时间")
    frp_error_message = models.TextField(blank=True, help_text="FRP错误信息")

    # 分组和项目
    group = models.CharField(max_length=100, blank=True, verbose_name='设备分组')
    tags = models.JSONField(default=list, verbose_name='标签')
    auto_deploy_project = models.ForeignKey(
        'Project', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='自动部署项目'
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '设备'
        verbose_name_plural = '设备列表'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['device_id']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.name or self.device_id} ({self.get_status_display()})"
    
    @property
    def is_online(self):
        """判断设备是否在线（2分钟内有心跳）"""
        if not self.last_heartbeat:
            return False
        return (timezone.now() - self.last_heartbeat).total_seconds() < 120
    
    @property
    def computed_status(self):
        """动态计算设备状态（根据心跳判断真实在线状态）"""
        if not self.is_online:
            return 'offline'
        return self.status if self.status != 'offline' else 'online'
    
    @property
    def computed_service_status(self):
        """动态计算服务状态（离线时服务状态为未知）"""
        if not self.is_online:
            return 'unknown'
        return self.service_status

    @property
    def ssh_connection_string(self):
        """生成 SSH 连接命令"""
        if not self.frp_enabled or not self.frp_ssh_port:
            return None

        frp_config = FrpServerConfig.objects.filter(is_active=True).first()
        if not frp_config:
            return None

        # 假设默认用户名为 jetson
        return f"ssh -p {self.frp_ssh_port} jetson@{frp_config.server_addr}"

    @property
    def web_access_url(self):
        """生成 Web 访问地址"""
        if not self.frp_enabled or not self.frp_web_port:
            return None

        frp_config = FrpServerConfig.objects.filter(is_active=True).first()
        if not frp_config:
            return None

        return f"http://{frp_config.server_addr}:{self.frp_web_port}"


class DeploymentTask(models.Model):
    """部署任务"""
    
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('downloading', '下载中'),
        ('configuring', '配置中'),
        ('starting', '启动中'),
        ('checking', '检查中'),
        ('completed', '完成'),
        ('failed', '失败'),
    ]
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='设备')
    target_version = models.CharField(max_length=50, verbose_name='目标版本')
    config = models.JSONField(default=dict, verbose_name='部署配置')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.IntegerField(default=0, verbose_name='进度(%)')
    message = models.TextField(blank=True, verbose_name='状态消息')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    
    class Meta:
        verbose_name = '部署任务'
        verbose_name_plural = '部署任务列表'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.device.device_id} -> {self.target_version} ({self.get_status_display()})"


class UpdateTask(models.Model):
    """更新任务"""
    
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('downloading', '下载中'),
        ('installing', '安装中'),
        ('success', '成功'),
        ('failed', '失败'),
        ('rolled_back', '已回滚'),
    ]
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='设备')
    from_version = models.CharField(max_length=50, verbose_name='原版本')
    target_version = models.CharField(max_length=50, verbose_name='目标版本')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.IntegerField(default=0, verbose_name='进度(%)')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    
    class Meta:
        verbose_name = '更新任务'
        verbose_name_plural = '更新任务列表'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.device.device_id}: {self.from_version} -> {self.target_version}"


class DeviceLog(models.Model):
    """设备日志"""
    
    LEVEL_CHOICES = [
        ('DEBUG', '调试'),
        ('INFO', '信息'),
        ('WARNING', '警告'),
        ('ERROR', '错误'),
        ('CRITICAL', '严重'),
    ]
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='设备')
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, verbose_name='级别')
    message = models.TextField(verbose_name='日志内容')
    timestamp = models.DateTimeField(default=timezone.now, verbose_name='时间戳')
    
    class Meta:
        verbose_name = '设备日志'
        verbose_name_plural = '设备日志列表'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['level', '-timestamp']),
        ]
    
    def __str__(self):
        return f"[{self.level}] {self.device.device_id}: {self.message[:50]}"


class ProjectConfig(models.Model):
    """项目配置"""
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='configs', verbose_name='项目')
    key = models.CharField(max_length=100, verbose_name='配置键')
    value = models.TextField(verbose_name='配置值')
    description = models.CharField(max_length=200, blank=True, verbose_name='描述')
    is_secret = models.BooleanField(default=False, verbose_name='是否敏感')
    
    class Meta:
        verbose_name = '项目配置'
        verbose_name_plural = '项目配置列表'
        unique_together = ['project', 'key']
    
    def __str__(self):
        return f"{self.project.name}.{self.key}"


class ProjectDeployment(models.Model):
    """项目部署记录"""
    
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('pulling_image', '拉取镜像'),
        ('pulling_code', '拉取代码'),
        ('configuring', '配置中'),
        ('starting', '启动中'),
        ('running', '运行中'),
        ('completed', '完成'),
        ('failed', '失败'),
    ]
    
    TASK_TYPE_CHOICES = [
        ('deploy', '部署'),
        ('restart', '重启'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, verbose_name='项目', null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='设备')
    task_type = models.CharField(max_length=20, choices=TASK_TYPE_CHOICES, default='deploy', verbose_name='任务类型')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.IntegerField(default=0, verbose_name='进度(%)')
    message = models.TextField(blank=True, verbose_name='状态消息')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    
    deployed_version = models.CharField(max_length=50, verbose_name='部署版本')
    git_commit = models.CharField(max_length=40, blank=True, verbose_name='Git提交')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    
    class Meta:
        verbose_name = '项目部署'
        verbose_name_plural = '项目部署列表'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.project.name} -> {self.device.device_id} ({self.status})"


class DeviceConfigHistory(models.Model):
    """设备配置历史记录"""

    STATUS_CHOICES = [
        ('pending', '待应用'),
        ('success', '成功'),
        ('failed', '失败'),
    ]

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='config_history',
        verbose_name='设备'
    )

    # 配置数据（JSON格式）
    # 示例结构:
    # {
    #   "cameras": {
    #     "样品盘": "192.168.31.201",
    #     "前处理": "192.168.31.202",
    #     "提取-纯化": "192.168.31.203",
    #     "孔板传送": "192.168.31.204",
    #     "反应体系构建": "192.168.31.205"
    #   },
    #   "plc": {"host": "192.168.31.29", "port": 9088},
    #   "backend": {"host": "127.0.0.1", "port": 8088}
    # }
    config_data = models.JSONField(verbose_name='配置数据')

    # 元数据
    applied_by = models.CharField(max_length=100, verbose_name='操作人')
    applied_at = models.DateTimeField(auto_now_add=True, verbose_name='应用时间')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='状态'
    )
    error_message = models.TextField(blank=True, verbose_name='错误信息')

    # 标记当前生效的配置
    is_active = models.BooleanField(default=False, verbose_name='当前生效')

    class Meta:
        verbose_name = '设备配置历史'
        verbose_name_plural = '设备配置历史列表'
        ordering = ['-applied_at']
        indexes = [
            models.Index(fields=['device', '-applied_at']),
            models.Index(fields=['device', 'is_active']),
        ]

    def __str__(self):
        return f"{self.device.device_id} - {self.get_status_display()} ({self.applied_at})"


class FrpServerConfig(models.Model):
    """FRP 服务器配置（全局唯一）"""

    # 服务器信息
    server_addr = models.CharField(max_length=255, help_text="FRP服务器地址")
    server_port = models.IntegerField(help_text="FRP服务器端口")
    token = models.CharField(max_length=255, help_text="认证Token")

    # 端口池配置
    port_pool_start = models.IntegerField(help_text="端口池起始")
    port_pool_end = models.IntegerField(help_text="端口池结束")

    # 状态
    is_active = models.BooleanField(default=True)
    config_version = models.IntegerField(default=1, help_text="配置版本号")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # 备注
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "FRP服务器配置"
        verbose_name_plural = "FRP服务器配置"

    def __str__(self):
        return f"{self.server_addr}:{self.server_port}"

    @property
    def available_ports(self):
        """获取可用端口列表"""
        all_ports = set(range(self.port_pool_start, self.port_pool_end + 1))
        used_ports = set()

        # 收集已使用的端口
        for device in Device.objects.filter(frp_enabled=True):
            if device.frp_ssh_port:
                used_ports.add(device.frp_ssh_port)
            if device.frp_web_port:
                used_ports.add(device.frp_web_port)

        return sorted(all_ports - used_ports)

    @property
    def total_ports(self):
        """端口池总容量"""
        return max(self.port_pool_end - self.port_pool_start + 1, 0)
