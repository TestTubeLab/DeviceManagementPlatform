import request from './request'

// 项目接口
export interface Project {
  id: number
  name: string
  description: string
  version: string
  status: 'draft' | 'active' | 'archived'
  docker_image: number | null
  docker_image_info?: {
    id: number
    name: string
    tag: string
    full_name: string
  }
  local_image_name: string  // 本地预装镜像名（如 newserver:latest）
  code_package: number | null
  code_package_info?: {
    id: number
    name: string
    version: string
    size_mb: number
  }
  code_mount_path: string
  git_repo: string
  git_branch: string
  work_dir: string
  start_command: string
  container_name: string
  container_config: {
    runtime?: string          // 'nvidia' 启用GPU
    network_mode?: string     // 'host' 或空
    privileged?: boolean      // 特权模式
    restart_policy?: string   // 重启策略
    ports?: Record<string, number>
    environment?: Record<string, string>
    volumes?: Record<string, string>
    devices?: string[]
  }
  configs?: ProjectConfig[]
  deployed_devices_count?: number
  created_by: string
  created_at: string
  updated_at: string
}

export interface ProjectConfig {
  id?: number
  project?: number
  key: string
  value: string
  description: string
  is_secret: boolean
}

export interface ProjectDeployment {
  id: number
  project: number
  project_info?: {
    id: number
    name: string
    version: string
  }
  device: number
  device_info?: {
    id: number
    device_id: string
    name: string
  }
  status: string
  progress: number
  message: string
  error_message: string
  deployed_version: string
  git_commit: string
  created_at: string
  updated_at: string
  completed_at: string | null
}

// 获取项目列表
export const getProjects = (params?: any) => {
  return request.get<any, { count: number, results: Project[] }>('/projects/', { params })
}

// 获取项目详情
export const getProject = (id: number) => {
  return request.get<any, Project>(`/projects/${id}/`)
}

// 创建项目
export const createProject = (data: Partial<Project>) => {
  return request.post<any, Project>('/projects/', data)
}

// 更新项目
export const updateProject = (id: number, data: Partial<Project>) => {
  return request.patch<any, Project>(`/projects/${id}/`, data)
}

// 删除项目
export const deleteProject = (id: number) => {
  return request.delete(`/projects/${id}/`)
}

// 部署项目到设备
export const deployProjectToDevices = (projectId: number, deviceIds: string[]) => {
  return request.post(`/projects/${projectId}/deploy_to_devices/`, {
    device_ids: deviceIds
  })
}

// 设置项目配置
export const setProjectConfig = (projectId: number, configs: Omit<ProjectConfig, 'id' | 'project'>[]) => {
  return request.post(`/projects/${projectId}/set_config/`, { configs })
}

// 获取项目部署列表
export const getProjectDeployments = (params?: any) => {
  return request.get<any, { count: number, results: ProjectDeployment[] }>('/project-deployments/', { params })
}

// 获取项目部署详情
export const getProjectDeployment = (id: number) => {
  return request.get<any, ProjectDeployment>(`/project-deployments/${id}/`)
}

