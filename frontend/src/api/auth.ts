import request from './request'

interface LoginResponse {
  token: string
  user: {
    id: number
    username: string
    email: string
    is_staff: boolean
    is_superuser: boolean
  }
}

interface UserInfo {
  id: number
  username: string
  email: string
  is_staff: boolean
  is_superuser: boolean
}

// 登录
export function login(username: string, password: string): Promise<LoginResponse> {
  return request.post('/auth/login/', { username, password })
}

// 登出
export function logout(): Promise<void> {
  return request.post('/auth/logout/')
}

// 获取当前用户信息
export function getUserInfo(): Promise<UserInfo> {
  return request.get('/auth/user/')
}

// 检查是否已登录
export function isLoggedIn(): boolean {
  return !!localStorage.getItem('token')
}

// 获取存储的用户信息
export function getStoredUser(): UserInfo | null {
  const userStr = localStorage.getItem('user')
  if (userStr) {
    try {
      return JSON.parse(userStr)
    } catch {
      return null
    }
  }
  return null
}

// 清除登录信息
export function clearAuth(): void {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

