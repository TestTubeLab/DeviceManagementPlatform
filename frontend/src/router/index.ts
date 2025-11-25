import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '监控仪表盘', icon: 'DataLine' }
      },
      {
        path: 'devices',
        name: 'DeviceList',
        component: () => import('@/views/DeviceList.vue'),
        meta: { title: '设备管理', icon: 'Monitor' }
      },
      {
        path: 'devices/:id',
        name: 'DeviceDetail',
        component: () => import('@/views/DeviceDetail.vue'),
        meta: { title: '设备详情', hidden: true }
      },
      {
        path: 'images',
        name: 'ImageRegistry',
        component: () => import('@/views/ImageRegistry.vue'),
        meta: { title: '镜像仓库', icon: 'Box' }
      },
      {
        path: 'projects',
        name: 'ProjectManage',
        component: () => import('@/views/ProjectManage.vue'),
        meta: { title: '项目管理', icon: 'FolderOpened' }
      },
      {
        path: 'deploy',
        name: 'DeployCenter',
        component: () => import('@/views/DeployCenter.vue'),
        meta: { title: '部署中心', icon: 'Upload' }
      },
      {
        path: 'tasks',
        name: 'TaskManage',
        component: () => import('@/views/TaskManage.vue'),
        meta: { title: '任务管理', icon: 'List' }
      },
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

