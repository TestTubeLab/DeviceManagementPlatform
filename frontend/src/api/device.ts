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

// 获取容器日志
export const getContainerLogs = (deviceId: string) => {
  return request.get<any, { device_id: string, logs: Array<{level: string, message: string, timestamp: string}> }>(`/devices/${deviceId}/container_logs/`)
}

// 更新设备 Agent
export const updateAgent = (deviceId: string) => {
  return request.post(`/devices/${deviceId}/update_agent/`)
}

// ==================== 配置管理 API ====================

// 配置数据类型
export interface DeviceConfig {
  cameras: {
    [name: string]: string  // 相机名 -> IP
  }
  plc: {
    host: string
    port: number
  }
  backend: {
    host: string
    port: number
  }
}

// 配置历史记录类型
export interface ConfigHistory {
  id: number
  device: number
  device_name: string
  device_id: string
  config_data: DeviceConfig
  applied_by: string
  applied_at: string
  status: 'pending' | 'success' | 'failed'
  status_display: string
  error_message: string
  is_active: boolean
}

// 获取当前配置
export const getCurrentConfig = (deviceId: string) => {
  return request.get<any, DeviceConfig>(`/devices/${deviceId}/current_config/`)
}

// 应用新配置（立即生效）
export const applyConfig = (deviceId: string, config: DeviceConfig) => {
  return request.post<any, { message: string, config_id: number }>(
    `/devices/${deviceId}/apply_config/`,
    config
  )
}

// 获取配置历史
export const getConfigHistory = (deviceId: string) => {
  return request.get<any, ConfigHistory[]>(`/devices/${deviceId}/config_history/`)
}

// 回滚到历史配置
export const rollbackConfig = (deviceId: string, configId: number) => {
  return request.post<any, { message: string, config_id: number }>(
    `/devices/${deviceId}/rollback_config/`,
    { config_id: configId }
  )
}

