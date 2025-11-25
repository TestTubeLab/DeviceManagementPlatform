// 设备状态类型
export type DeviceStatus = 'waiting' | 'deploying' | 'online' | 'offline' | 'updating' | 'error'

// 设备信息
export interface Device {
  id: number
  device_id: string
  name: string
  location: string
  mac_address: string
  ip_address: string
  status: DeviceStatus
  current_version: string
  last_heartbeat: string | null
  cpu_usage: number
  memory_usage: number
  disk_usage: number
  config: Record<string, any>
  created_at: string
  updated_at: string
}

// 部署任务状态
export type DeploymentStatus = 'pending' | 'downloading' | 'configuring' | 'starting' | 'checking' | 'completed' | 'failed'

// 部署任务
export interface DeploymentTask {
  id: number
  device: number
  target_version: string
  config: Record<string, any>
  status: DeploymentStatus
  progress: number
  message: string
  error_message: string
  created_at: string
  updated_at: string
  completed_at: string | null
}

// 更新任务状态
export type UpdateStatus = 'pending' | 'downloading' | 'installing' | 'success' | 'failed' | 'rolled_back'

// 更新任务
export interface UpdateTask {
  id: number
  device: number
  from_version: string
  target_version: string
  status: UpdateStatus
  progress: number
  error_message: string
  created_at: string
  updated_at: string
  completed_at: string | null
}

// 设备日志级别
export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

// 设备日志
export interface DeviceLog {
  id: number
  device: number
  level: LogLevel
  message: string
  timestamp: string
}

// Docker镜像
export interface DockerImage {
  id: number
  name: string
  tag: string
  full_name: string
  size: number
  size_mb: number
  file_path: string
  description: string
  created_by: string
  is_active: boolean
  uploaded_at: string
}

