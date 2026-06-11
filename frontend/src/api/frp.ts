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
  web_port_pool_start?: number | null
  web_port_pool_end?: number | null
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
