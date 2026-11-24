import request from './request'
import type { FrpOverview } from '@/types'

export const getFrpOverview = () => {
  return request.get<any, FrpOverview>('/frp/')
}

export const updateFrpConfig = (data: {
  server_addr?: string
  server_port?: number
  token?: string
  port_pool_start?: number
  port_pool_end?: number
  is_active?: boolean
  description?: string
}) => {
  return request.patch<any, FrpOverview>('/frp/config/', data)
}

export const syncFrpConfig = () => {
  return request.post<any, FrpOverview>('/frp/sync/')
}

export const controlFrpService = (action: 'start' | 'stop' | 'restart') => {
  return request.post<any, FrpOverview>('/frp/service/', { action })
}

export const setFrpPublicAccess = (deviceId: string, enabled: boolean) =>
  request.patch<any, { message: string; firewall: FrpOverview['firewall'] }>(
    `/frp/${deviceId}/public-access/`, { enabled },
  )

export const updateFrpPort = (deviceId: string, field: 'ssh_port' | 'web_port', port: number) =>
  request.patch<any, { message: string; firewall: FrpOverview['firewall'] }>(
    `/frp/${deviceId}/ports/`, { [field]: port },
  )

export const resetFrpPorts = (deviceId: string) =>
  request.post<any, { message: string; ssh_port: number; web_port: number; firewall: FrpOverview['firewall'] }>(
    `/frp/${deviceId}/ports/reset/`,
  )
