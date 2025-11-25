import request from './request'
import type { DeploymentTask, UpdateTask } from '@/types'

// 获取部署任务列表
export const getDeploymentTasks = () => {
  return request.get<any, { count: number, results: DeploymentTask[] }>('/deployments/')
    .then(res => res.results || [])
}

// 创建部署任务
export const createDeploymentTask = (data: {
  device: number
  target_version: string
  config?: Record<string, any>
}) => {
  return request.post<any, DeploymentTask>('/deployments/', data)
}

// 更新部署任务进度
export const updateDeploymentProgress = (taskId: number, data: {
  status?: string
  progress?: number
  message?: string
  error_message?: string
}) => {
  return request.post(`/deployments/${taskId}/update_progress/`, data)
}

// 获取更新任务列表
export const getUpdateTasks = () => {
  return request.get<any, { count: number, results: UpdateTask[] }>('/updates/')
    .then(res => res.results || [])
}

// 创建更新任务
export const createUpdateTask = (data: {
  device: number
  from_version: string
  target_version: string
}) => {
  return request.post<any, UpdateTask>('/updates/', data)
}

// 更新任务进度
export const updateTaskProgress = (taskId: number, data: {
  status?: string
  progress?: number
  error_message?: string
}) => {
  return request.post(`/updates/${taskId}/update_progress/`, data)
}

