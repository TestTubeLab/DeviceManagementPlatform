"""
管理应用URL配置
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import device_ssh, views
from .platform_updates import PlatformReleaseView, PlatformUpdateView, platform_health

router = DefaultRouter()
router.register(r'devices', views.DeviceViewSet)
router.register(r'deployments', views.DeploymentTaskViewSet)
router.register(r'updates', views.UpdateTaskViewSet)
router.register(r'logs', views.DeviceLogViewSet)
router.register(r'system-logs', views.SystemLogViewSet)
router.register(r'images', views.DockerImageViewSet)
router.register(r'code-packages', views.CodePackageViewSet)
router.register(r'projects', views.ProjectViewSet)
router.register(r'project-deployments', views.ProjectDeploymentViewSet)
router.register(r'frp', views.FrpManagementViewSet, basename='frp')

urlpatterns = [
    path('platform/health/', platform_health, name='platform_health'),
    path('platform/release/', PlatformReleaseView.as_view(), name='platform_release'),
    path('platform/updates/', PlatformUpdateView.as_view(), name='platform_update'),
    path('devices/<str:device_id>/ssh-management/', device_ssh.management_view),
    path('devices/<str:device_id>/ssh-management/enrollment/', device_ssh.create_enrollment),
    path('devices/<str:device_id>/ssh-management/tasks/', device_ssh.create_task),
    path('agent/ssh-management/<str:device_id>/poll/', device_ssh.poll_task),
    path('agent/ssh-management/<str:device_id>/receipt/', device_ssh.report_task),
    path('', include(router.urls)),
    path('install.sh', views.get_install_script, name='install_script'),
    path('agent/device-agent.py', views.get_agent_script, name='agent_script'),
    # Agent 版本管理
    path('agent/version/', views.agent_version, name='agent_version'),
    path('agent/download/', views.agent_download, name='agent_download'),
    # 用户认证
    path('auth/login/', views.user_login, name='user_login'),
    path('auth/logout/', views.user_logout, name='user_logout'),
    path('auth/user/', views.user_info, name='user_info'),
]


