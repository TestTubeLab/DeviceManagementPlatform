"""
设备管理核心数据模型
"""
from django.db import models
from django.utils import timezone


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
