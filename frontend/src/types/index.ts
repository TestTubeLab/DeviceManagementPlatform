// 设备状态类型
export type DeviceStatus = 'waiting' | 'deploying' | 'online' | 'offline' | 'updating' | 'error'

// 容器状态类型
export type ContainerStatus = 'running' | 'stopped' | 'not_found' | 'error'

// 服务状态类型
export type ServiceStatus = 'healthy' | 'unhealthy' | 'unknown'

// FRP 状态类型
export type FrpStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

// FRP 服务状态类型
export type FrpServiceStatus = 'running' | 'exited' | 'created' | 'restarting' | 'paused' | 'dead' | 'missing' | 'error' | 'unknown'

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
  // 服务监控信息
  container_status: ContainerStatus
  container_name: string
  container_uptime: string
  service_status: ServiceStatus
  service_response_time: number
  health_check_url: string
  last_health_check: string | null
  config: Record<string, any>
  group: string
  tags: string[]
  auto_deploy_project: number | null
  created_at: string
  updated_at: string
  // 动态计算字段（后端根据心跳时间实时计算）
  is_online?: boolean
  computed_status?: DeviceStatus
  computed_service_status?: ServiceStatus
  agent_version?: string
  // FRP 远程连接相关字段
  frp_enabled?: boolean
  frp_ssh_port?: number | null
  frp_web_port?: number | null
  frp_status?: FrpStatus
  frp_last_check?: string | null
  frp_error_message?: string
  ssh_connection_string?: string | null
}

export interface FrpConfig {
  id: number
  server_addr: string
  server_port: number
  token: string
  port_pool_start: number
  port_pool_end: number
  is_active: boolean
  config_version: number
  description: string
  available_ports: number[]
  total_ports: number
  used_ports_count: number
  available_ports_count: number
  enabled_devices_count: number
  connected_devices_count: number
}

export interface FrpService {
  container_name: string
  status: FrpServiceStatus
  running: boolean
  started_at: string | null
  error?: string
}

export interface FrpOverview {
  config: FrpConfig
  service: FrpService
  devices: Device[]
  message?: string
  backup_path?: string
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


