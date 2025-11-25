import request from './request'
import type { DeviceLog } from '@/types'

// 获取日志列表
export const getLogs = (params?: { device_id?: string }) => {
  return request.get<any, { count: number, results: DeviceLog[] }>('/logs/', { params })
    .then(res => res.results || [])
}

// 创建日志
export const createLog = (data: {
  device: number
  level: string
  message: string
}) => {
  return request.post<any, DeviceLog>('/logs/', data)
}

