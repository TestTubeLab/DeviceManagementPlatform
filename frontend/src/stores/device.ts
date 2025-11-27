import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Device } from '@/types'
import { getDevices, getDevice } from '@/api/device'

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<Device[]>([])
  const currentDevice = ref<Device | null>(null)
  const loading = ref(false)

  // 加载设备列表
  const loadDevices = async () => {
    loading.value = true
    try {
      const response = await getDevices()
      devices.value = response.results || []
    } catch (error) {
      console.error('加载设备列表失败:', error)
    } finally {
      loading.value = false
    }
  }

  // 加载设备详情
  const loadDevice = async (deviceId: string) => {
    loading.value = true
    try {
      currentDevice.value = await getDevice(deviceId)
    } catch (error) {
      console.error('加载设备详情失败:', error)
    } finally {
      loading.value = false
    }
  }

  // 获取在线设备数
  const onlineCount = () => {
    return devices.value.filter(d => d.status === 'online').length
  }

  // 获取离线设备数
  const offlineCount = () => {
    return devices.value.filter(d => d.status === 'offline').length
  }

  // 获取待部署设备数
  const waitingCount = () => {
    return devices.value.filter(d => d.status === 'waiting').length
  }

  return {
    devices,
    currentDevice,
    loading,
    loadDevices,
    loadDevice,
    onlineCount,
    offlineCount,
    waitingCount,
  }
})


