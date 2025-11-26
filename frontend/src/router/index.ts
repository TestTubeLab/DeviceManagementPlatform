import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true }
  },
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
        path: 'projects',
        name: 'ProjectManage',
        component: () => import('@/views/ProjectManage.vue'),
        meta: { title: '项目管理', icon: 'FolderOpened' }
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

// 路由守卫 - 检查登录状态
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const isPublic = to.meta.public === true
  
  if (!token && !isPublic) {
    // 未登录且不是公开页面，跳转登录
    next('/login')
  } else if (token && to.path === '/login') {
    // 已登录但访问登录页，跳转首页
    next('/')
  } else {
    next()
  }
})

export default router

