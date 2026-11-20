import request from './request'
import type { Device } from '@/types'

export interface LogPage<T> { count: number; results: T[]; next?: string | null }
export interface LogFilters {
  start_time?: string
  end_time?: string
  level?: string
  search?: string
  page?: number
  page_size?: number
}
export interface PlatformLog {
  id: number
  timestamp: string
  level: string
  module: string
  action: string
  actor: string
  target: string
  result: 'submitted' | 'success' | 'failed'
  message: string
  detail: string
  device_id: string
  task_id: string
}
export interface SavedDeviceLog {
  id: number
  device: number
  device_id: string
  device_name: string
  level: string
  message: string
  timestamp: string
}
export type JournalSource = 'agent' | 'frpc' | 'docker' | 'system'
export interface JournalResult {
  content: string
  returned_lines: number
  truncated: boolean
  source: JournalSource
  collected_at: string
}
export interface BusinessFiles { dates: string[]; files: Record<string, string[]> }
export interface BusinessContent { content: string; total_lines: number; returned_lines: number; truncated?: boolean }
export interface BusinessSearch {
  total_matches: number
  matches: Array<{ date: string; file: string; line_num: number; content: string }>
  returned_matches?: number
  truncated?: boolean
}
export interface BusinessArchive { content: string; filename: string }
export interface LogTask<T> {
  task_id: string | number
  task_type: 'list' | 'read' | 'search' | 'download' | 'journal'
  status: 'pending' | 'processing' | 'completed' | 'failed'
  result: T
  error_message?: string
}

export const logModuleLabels: Record<string, string> = {
  auth: '认证', device: '设备', project: '项目', image: '镜像', package: '代码包',
  deployment: '部署', frp: 'FRP', system: '系统',
}
export const logActionLabels: Record<string, string> = {
  create: '创建', update: '更新', partial_update: '修改', destroy: '删除',
  deploy_to_devices: '部署到设备', restart: '重启', apply_config: '应用配置',
  rollback_config: '回滚配置', update_agent: '升级 Agent', setup_factory_config: '设置出厂配置',
  set_frp_enabled: '设置 FRP 开关', allocate_frp_ports: '分配 FRP 端口', update_config: '更新配置',
  sync: '同步', service_control: '服务控制', user_login: '登录', user_logout: '退出登录',
  update_progress: '更新部署进度', config_result: '配置执行结果', progress: '进度上报',
  report_system_task: '系统任务结果', push_to_device: '推送镜像到设备', batch_update: '批量更新设备',
}

/** Paginated APIs keep api/log.ts#getLogs and its array return contract intact. */
export const getSystemLogs = (params: LogFilters & { module?: string; actor?: string; result?: string }, signal: AbortSignal) =>
  request.get<unknown, LogPage<PlatformLog>>('/system-logs/', { params, signal })

export const getSystemLog = (id: string, signal: AbortSignal) =>
  request.get<unknown, PlatformLog>(`/system-logs/${encodeURIComponent(id)}/`, { signal })

export const getLogsPage = (params: LogFilters & { device_id: string }, signal: AbortSignal) =>
  request.get<unknown, LogPage<SavedDeviceLog>>('/logs/', { params, signal })

/** Load every device page without overlapping requests or following external URLs. */
export async function getLogDevices(signal: AbortSignal): Promise<Device[]> {
  const devices: Device[] = []
  let page = 1
  while (true) {
    const result = await request.get<unknown, LogPage<Device>>('/devices/', { params: { page }, signal })
    devices.push(...result.results)
    if (!result.next && devices.length >= result.count) return devices
    if (!result.results.length) return devices
    page += 1
  }
}

export const getLogDevice = (deviceId: string, signal: AbortSignal) =>
  request.get<unknown, Device>(`/devices/${encodeURIComponent(deviceId)}/`, { signal })

/** Existing business log endpoints, with cancellation and typed task results. */
export const createLogTask = (
  deviceId: string,
  operation: 'list_logs' | 'read_log' | 'search_logs' | 'download_log',
  body: Record<string, unknown>,
  signal: AbortSignal,
) => request.post<unknown, { task_id: string | number; message: string }>(
  `/devices/${encodeURIComponent(deviceId)}/${operation}/`, body, { signal },
)

export const collectServiceLogs = (deviceId: string, body: {
  source: JournalSource; start_time?: string; end_time?: string; lines: number; level?: string; keyword?: string
}, signal: AbortSignal) => request.post<unknown, { task_id: string; message: string }>(
  `/devices/${encodeURIComponent(deviceId)}/service_logs/`, body, { signal },
)

/** Poll once per second. The caller supplies a signal with a 60-second deadline. */
export async function waitForLogTask<T>(deviceId: string, taskId: string | number, signal: AbortSignal): Promise<T> {
  while (true) {
    signal.throwIfAborted()
    const task = await request.get<unknown, LogTask<T>>(
      `/devices/${encodeURIComponent(deviceId)}/log_task_result/`, { params: { task_id: taskId }, signal },
    )
    if (task.status === 'failed') throw new Error(task.error_message || '日志任务失败')
    if (task.status === 'completed') return task.result
    await new Promise<void>((resolve, reject) => {
      const abort = () => { window.clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
      const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 1000)
      signal.addEventListener('abort', abort, { once: true })
      if (signal.aborted) abort()
    })
  }
}

export function supportsServiceLogs(version?: string): boolean {
  const match = version?.trim().match(/^v?(\d+)\.(\d+)\.(\d+)$/)
  if (!match) return false
  const parts = match.slice(1).map(Number)
  return parts[0]! > 1 || (parts[0] === 1 && (parts[1]! > 7 || (parts[1] === 7 && parts[2]! >= 3)))
}
