import request from './request'

// 代码包接口
export interface CodePackage {
  id: number
  name: string
  version: string
  file_path: string
  size: number
  size_mb: number
  checksum: string
  description: string
  created_by: string
  uploaded_at: string
}

// 获取代码包列表
export const getCodePackages = (params?: any) => {
  return request.get<any, { count: number, results: CodePackage[] }>('/code-packages/', { params })
}

// 获取代码包详情
export const getCodePackage = (id: number) => {
  return request.get<any, CodePackage>(`/code-packages/${id}/`)
}

// 上传代码包
export const uploadCodePackage = (
  file: File,
  name: string,
  version: string,
  description: string = '',
  onProgress?: (progress: number) => void
) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('name', name)
  formData.append('version', version)
  formData.append('description', description)

  return request.post<any, CodePackage>('/code-packages/upload/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(progress)
      }
    }
  })
}

// 删除代码包
export const deleteCodePackage = (id: number) => {
  return request.delete(`/code-packages/${id}/`)
}

// 下载代码包URL
export const getCodePackageDownloadUrl = (id: number) => {
  return `/api/code-packages/${id}/download/`
}


