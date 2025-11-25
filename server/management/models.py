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
    
    # 配置信息（JSON字段，存储设备特定配置）
    config = models.JSONField(default=dict, verbose_name='设备配置')
    
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
    
    def is_online(self):
        """判断设备是否在线（5分钟内有心跳）"""
        if not self.last_heartbeat:
            return False
        return (timezone.now() - self.last_heartbeat).total_seconds() < 300


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
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, verbose_name='项目')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='设备')
    
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
