export const ACTIVE_PROJECT_DEPLOYMENT_STATUSES = [
  'pending',
  'pulling_image',
  'pulling_code',
  'configuring',
  'starting',
] as const

export const ACTIVE_PROJECT_DEPLOYMENT_STATUS_QUERY = ACTIVE_PROJECT_DEPLOYMENT_STATUSES.join(',')

export const isProjectDeploymentActive = (status: string) => {
  return ACTIVE_PROJECT_DEPLOYMENT_STATUSES.includes(
    status as (typeof ACTIVE_PROJECT_DEPLOYMENT_STATUSES)[number]
  )
}

export const getProjectDeploymentStatusType = (status: string) => {
  const typeMap: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
    pending: 'info',
    pulling_image: 'warning',
    pulling_code: 'warning',
    configuring: 'warning',
    starting: 'warning',
    running: 'success',
    completed: 'success',
    failed: 'danger',
  }

  return typeMap[status] || 'info'
}

export const getProjectDeploymentStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    pending: '等待中',
    pulling_image: '拉取镜像',
    pulling_code: '下载代码',
    configuring: '配置中',
    starting: '启动中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
  }

  return textMap[status] || status
}

export const getProjectDeploymentProgressStatus = (status: string) => {
  if (status === 'completed' || status === 'running') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}
