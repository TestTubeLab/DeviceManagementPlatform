import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api',
  timeout: 600000,  // 10分钟，大文件上传需要更长时间
})

// 请求拦截器 - 添加 Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Token ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理 401 未授权
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    const status = error.response?.status
    
    if (status === 401) {
      // 未授权，清除 token 并跳转登录
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      
      // 避免重复跳转
      if (router.currentRoute.value.path !== '/login') {
        ElMessage.error('登录已过期，请重新登录')
        router.push('/login')
      }
      return Promise.reject(error)
    }
    
    if (status === 403) {
      ElMessage.error('没有权限访问')
      return Promise.reject(error)
    }
    
    const message = error.response?.data?.error || error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default request


