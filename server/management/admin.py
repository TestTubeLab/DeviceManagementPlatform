"""
Django Admin配置
"""
from django.contrib import admin
from .models import Device, DeploymentTask, UpdateTask, DeviceLog


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'name', 'status', 'current_version', 'is_online', 'last_heartbeat']
    list_filter = ['status', 'created_at']
    search_fields = ['device_id', 'name', 'mac_address', 'ip_address']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = [
        ('基本信息', {
            'fields': ['device_id', 'name', 'location', 'mac_address', 'ip_address']
        }),
        ('状态信息', {
            'fields': ['status', 'current_version', 'last_heartbeat']
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
