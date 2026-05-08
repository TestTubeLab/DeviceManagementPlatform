import type { Device, DeviceStatus, ServiceStatus } from '@/types'

type DeviceStatusSource = Pick<Device, 'status' | 'computed_status' | 'is_online'>
type DeviceServiceStatusSource = DeviceStatusSource & Pick<Device, 'service_status' | 'computed_service_status'>
type DeviceContainerStatusSource = DeviceStatusSource & Pick<Device, 'container_status'>
type DeviceFrpStatusSource = DeviceStatusSource & Pick<Device, 'frp_status'>

export type DisplayContainerStatus = Device['container_status'] | 'unknown'
export type DisplayFrpStatus = NonNullable<Device['frp_status']> | 'offline'

export const getDeviceDisplayStatus = (device: DeviceStatusSource): DeviceStatus => {
  return device.computed_status ?? device.status
}

export const isDeviceCurrentlyOnline = (device: DeviceStatusSource): boolean => {
  if (typeof device.is_online === 'boolean') {
    return device.is_online
  }
  return getDeviceDisplayStatus(device) !== 'offline'
}

export const getDeviceDisplayServiceStatus = (device: DeviceServiceStatusSource): ServiceStatus => {
  if (!isDeviceCurrentlyOnline(device)) {
    return 'unknown'
  }
  return device.computed_service_status ?? device.service_status ?? 'unknown'
}

export const getDeviceDisplayContainerStatus = (device: DeviceContainerStatusSource): DisplayContainerStatus => {
  if (!isDeviceCurrentlyOnline(device)) {
    return 'unknown'
  }
  return device.container_status
}

export const getDeviceDisplayFrpStatus = (device: DeviceFrpStatusSource): DisplayFrpStatus => {
  if (!isDeviceCurrentlyOnline(device)) {
    return 'offline'
  }
  return device.frp_status ?? 'disconnected'
}
