import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Device, DeviceStatus } from '@/types'
import { getDevices, getDevice } from '@/api/device'
import { getDeviceDisplayStatus } from '@/utils/deviceStatus'

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
  const loadDevice = async (deviceId: string, silent = false) => {
    if (!silent) {
      loading.value = true
    }
    try {
      currentDevice.value = await getDevice(deviceId)
    } catch (error) {
      console.error('加载设备详情失败:', error)
    } finally {
      if (!silent) {
        loading.value = false
      }
    }
  }

  // 静默刷新设备状态（不显示loading）
  const refreshDevice = async (deviceId: string) => {
    try {
      currentDevice.value = await getDevice(deviceId)
    } catch (error) {
      console.error('刷新设备状态失败:', error)
    }
  }

  const countByStatus = (status: DeviceStatus) => {
    return devices.value.filter(device => getDeviceDisplayStatus(device) === status).length
  }

  // 获取在线设备数
  const onlineCount = () => {
    return countByStatus('online')
  }

  // 获取离线设备数
  const offlineCount = () => {
    return countByStatus('offline')
  }

  // 获取待部署设备数
  const waitingCount = () => {
    return countByStatus('waiting')
  }

  return {
    devices,
    currentDevice,
    loading,
    loadDevices,
    loadDevice,
    refreshDevice,
    onlineCount,
    offlineCount,
    waitingCount,
  }
})


