/**
 * 镜像管理 API
 */
import request from './request'
import type { DockerImage } from '@/types'

/**
 * 获取镜像列表
 */
export const getImages = () => {
  return request.get<any, { results: DockerImage[] }>('/images/')
}

/**
 * 获取单个镜像详情
 */
export const getImageDetail = (id: number) => {
  return request.get<any, DockerImage>(`/images/${id}/`)
}

/**
 * 上传镜像
 * @param formData 包含file字段的FormData对象
 * @param onProgress 上传进度回调函数
 */
export const uploadImage = (
  formData: FormData,
  onProgress?: (percent: number) => void
) => {
  return request.post<any, DockerImage>('/images/upload/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    onUploadProgress: (progressEvent) => {
      if (progressEvent.total && onProgress) {
        const percent = Math.round((progressEvent.loaded / progressEvent.total) * 100)
        onProgress(percent)
      }
    }
  })
}

/**
 * 删除镜像
 */
export const deleteImage = (id: number) => {
  return request.delete(`/images/${id}/`)
}

/**
 * 推送镜像到设备
 * @param imageId 镜像ID
 * @param deviceIds 设备ID数组
 * @param containerName 容器名称
 * @param containerConfig 容器配置
 */
export const pushImageToDevice = (
  imageId: number,
  data: {
    device_ids: string[]
    container_name?: string
    container_config?: Record<string, any>
  }
) => {
  return request.post(`/images/${imageId}/push_to_device/`, data)
}



