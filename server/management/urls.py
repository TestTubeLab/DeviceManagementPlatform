"""
管理应用URL配置
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'devices', views.DeviceViewSet)
router.register(r'deployments', views.DeploymentTaskViewSet)
router.register(r'updates', views.UpdateTaskViewSet)
router.register(r'logs', views.DeviceLogViewSet)
router.register(r'images', views.DockerImageViewSet)
router.register(r'code-packages', views.CodePackageViewSet)
router.register(r'projects', views.ProjectViewSet)
router.register(r'project-deployments', views.ProjectDeploymentViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('install.sh', views.get_install_script, name='install_script'),
    path('agent/device-agent.py', views.get_agent_script, name='agent_script'),
]

