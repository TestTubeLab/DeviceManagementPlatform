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

urlpatterns = [
    path('', include(router.urls)),
]

