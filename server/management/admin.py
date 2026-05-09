"""
Django Admin配置
"""
from django.contrib import admin
from django.utils import timezone
from datetime import timedelta
from .models import (
    Device, DeploymentTask, UpdateTask, DeviceLog, DockerImage,
    CodePackage, Project, ProjectConfig, ProjectDeployment, FrpServerConfig
)


class DeviceActualStatusFilter(admin.SimpleListFilter):
    title = '实时状态'
    parameter_name = 'actual_status'

    def lookups(self, request, model_admin):
        return (
            ('online', '在线'),
            ('offline', '离线'),
            ('waiting', '等待部署'),
            ('deploying', '部署中'),
            ('updating', '更新中'),
            ('error', '异常'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset

        heartbeat_threshold = timezone.now() - timedelta(seconds=120)
        online_queryset = queryset.filter(last_heartbeat__gte=heartbeat_threshold)
        offline_queryset = queryset.exclude(last_heartbeat__gte=heartbeat_threshold)

        if value == 'offline':
            return offline_queryset
        if value == 'online':
            return online_queryset.filter(status__in=['online', 'offline'])
        if value in ['waiting', 'deploying', 'updating', 'error']:
            return online_queryset.filter(status=value)

        return queryset


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'name', 'display_status', 'current_version', 'is_online', 'last_heartbeat']
    list_filter = [DeviceActualStatusFilter, 'created_at']
    search_fields = ['device_id', 'name', 'mac_address', 'ip_address']
    readonly_fields = ['created_at', 'updated_at', 'computed_status', 'is_online']
    
    fieldsets = [
        ('基本信息', {
            'fields': ['device_id', 'name', 'location', 'mac_address', 'ip_address']
        }),
        ('状态信息', {
            'fields': ['status', 'computed_status', 'is_online', 'current_version', 'last_heartbeat']
        }),
        ('分组和项目', {
            'fields': ['group', 'tags', 'auto_deploy_project']
        }),
        ('FRP', {
            'fields': ['frp_enabled', 'frp_ssh_port', 'frp_status', 'frp_last_check', 'frp_error_message']
        }),
        ('硬件指标', {
            'fields': ['cpu_usage', 'memory_usage', 'disk_usage']
        }),
        ('配置', {
            'fields': ['config'],
            'classes': ['collapse']
        }),
        ('时间戳', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    @admin.display(description='实时状态')
    def display_status(self, obj):
        status_text = dict(Device.STATUS_CHOICES).get(obj.computed_status, obj.computed_status)
        return status_text


@admin.register(DeploymentTask)
class DeploymentTaskAdmin(admin.ModelAdmin):
    list_display = ['device', 'target_version', 'status', 'progress', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['device__device_id', 'target_version']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']


@admin.register(UpdateTask)
class UpdateTaskAdmin(admin.ModelAdmin):
    list_display = ['device', 'from_version', 'target_version', 'status', 'progress', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['device__device_id', 'target_version']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']


@admin.register(DeviceLog)
class DeviceLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'level', 'message_short', 'timestamp']
    list_filter = ['level', 'timestamp']
    search_fields = ['device__device_id', 'message']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    
    def message_short(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_short.short_description = '消息'


@admin.register(DockerImage)
class DockerImageAdmin(admin.ModelAdmin):
    list_display = ['name', 'tag', 'size_mb', 'created_by', 'uploaded_at', 'is_active']
    list_filter = ['is_active', 'uploaded_at', 'created_by']
    search_fields = ['name', 'tag', 'description']
    readonly_fields = ['uploaded_at', 'file_path', 'full_name', 'size']
    
    def size_mb(self, obj):
        return f"{obj.size / (1024*1024):.2f} MB"
    size_mb.short_description = '文件大小'


@admin.register(CodePackage)
class CodePackageAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'size_mb', 'created_by', 'uploaded_at']
    list_filter = ['uploaded_at', 'created_by']
    search_fields = ['name', 'version', 'description']
    readonly_fields = ['uploaded_at', 'file_path', 'size', 'checksum']
    
    def size_mb(self, obj):
        return f"{obj.size / (1024*1024):.2f} MB"
    size_mb.short_description = '文件大小'


class ProjectConfigInline(admin.TabularInline):
    """项目配置内联编辑"""
    model = ProjectConfig
    extra = 1
    fields = ['key', 'value', 'description', 'is_secret']


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'status', 'docker_image', 'created_by', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description', 'git_repo']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ProjectConfigInline]
    
    fieldsets = [
        ('基本信息', {
            'fields': ['name', 'description', 'version', 'status']
        }),
        ('Docker配置', {
            'fields': ['docker_image', 'container_name', 'container_config']
        }),
        ('代码仓库', {
            'fields': ['git_repo', 'git_branch', 'work_dir', 'start_command']
        }),
        ('元数据', {
            'fields': ['created_by', 'created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(ProjectDeployment)
class ProjectDeploymentAdmin(admin.ModelAdmin):
    list_display = ['project', 'device', 'deployed_version', 'status', 'progress', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['project__name', 'device__device_id', 'deployed_version']
    readonly_fields = ['created_at', 'updated_at', 'completed_at', 'git_commit']
    
    fieldsets = [
        ('部署信息', {
            'fields': ['project', 'device', 'deployed_version', 'git_commit']
        }),
        ('状态', {
            'fields': ['status', 'progress', 'message', 'error_message']
        }),
        ('时间戳', {
            'fields': ['created_at', 'updated_at', 'completed_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(FrpServerConfig)
class FrpServerConfigAdmin(admin.ModelAdmin):
    list_display = ['server_addr', 'server_port', 'port_pool_start', 'port_pool_end', 'is_active', 'config_version', 'updated_at']
    list_filter = ['is_active', 'updated_at']
    search_fields = ['server_addr', 'description']
    readonly_fields = ['config_version', 'created_at', 'updated_at']
