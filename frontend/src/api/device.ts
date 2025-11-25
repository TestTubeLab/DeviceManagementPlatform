import request from './request'
import type { Device } from '@/types'

// 获取设备列表
export const getDevices = () => {
  return request.get<any, { count: number, results: Device[] }>('/devices/')
}

// 获取设备详情
export const getDevice = (deviceId: string) => {
  return request.get<any, Device>(`/devices/${deviceId}/`)
}

// 注册设备
export const registerDevice = (data: {
  device_id: string
  mac_address: string
  ip_address: string
  hostname?: string
}) => {
  return request.post('/devices/register/', data)
}

// 设备心跳
export const deviceHeartbeat = (deviceId: string, data: {
  version?: string
  cpu_usage?: number
  memory_usage?: number
  disk_usage?: number
}) => {
  return request.post(`/devices/${deviceId}/heartbeat/`, data)
}

// 批量更新设备
export const batchUpdateDevices = (data: {
  device_ids: string[]
  version: string
}) => {
  return request.post('/devices/batch_update/', data)
}

// 创建设备
export const createDevice = (data: Partial<Device>) => {
  return request.post('/devices/', data)
}

// 更新设备
export const updateDevice = (deviceId: string, data: Partial<Device>) => {
  return request.patch(`/devices/${deviceId}/`, data)
}

// 删除设备
export const deleteDevice = (deviceId: string) => {
  return request.delete(`/devices/${deviceId}/`)
}

// 重启设备服务
export const restartDevice = (deviceId: string) => {
  return request.post(`/devices/${deviceId}/restart/`)
}

