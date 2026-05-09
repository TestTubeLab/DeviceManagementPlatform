<template>
  <el-card class="device-card" shadow="hover" @click="$emit('click')">
    <div class="card-header">
      <div class="device-info">
        <el-icon class="device-icon" :class="statusClass">
          <Monitor />
        </el-icon>
        <div>
          <div class="device-name">{{ device.name || device.device_id }}</div>
          <div class="device-id">{{ device.device_id }}</div>
        </div>
      </div>
      <StatusBadge :status="deviceStatus" />
    </div>
    
    <el-divider style="margin: 12px 0" />
    
    <div class="card-body">
      <div class="info-row">
        <span class="label">服务状态:</span>
        <span class="value">
          <span class="service-indicator" :class="serviceStatusClass"></span>
          {{ serviceStatusText }}
        </span>
      </div>
      <div class="info-row">
        <span class="label">IP地址:</span>
        <span class="value">{{ device.ip_address || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="label">项目版本:</span>
        <span class="value">{{ device.current_version || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="label">Agent:</span>
        <span class="value">{{ device.agent_version || 'unknown' }}</span>
      </div>
      <div class="info-row">
        <span class="label">最后心跳:</span>
        <span class="value">{{ heartbeatText }}</span>
      </div>
    </div>
    
    <el-divider style="margin: 12px 0" />
    
    <div class="card-footer">
      <div class="resource-item">
        <span class="resource-label">CPU</span>
        <template v-if="isOnline">
          <el-progress :percentage="device.cpu_usage" :stroke-width="6" :show-text="false" />
          <span class="resource-value">{{ device.cpu_usage.toFixed(1) }}%</span>
        </template>
        <template v-else>
          <span class="resource-offline">离线</span>
          <span class="resource-value resource-value-muted">--</span>
        </template>
      </div>
      <div class="resource-item">
        <span class="resource-label">内存</span>
        <template v-if="isOnline">
          <el-progress :percentage="device.memory_usage" :stroke-width="6" :show-text="false" />
          <span class="resource-value">{{ device.memory_usage.toFixed(1) }}%</span>
        </template>
        <template v-else>
          <span class="resource-offline">离线</span>
          <span class="resource-value resource-value-muted">--</span>
        </template>
      </div>
      <div class="resource-item">
        <span class="resource-label">磁盘</span>
        <template v-if="isOnline">
          <el-progress :percentage="device.disk_usage" :stroke-width="6" :show-text="false" />
          <span class="resource-value">{{ device.disk_usage.toFixed(1) }}%</span>
        </template>
        <template v-else>
          <span class="resource-offline">离线</span>
          <span class="resource-value resource-value-muted">--</span>
        </template>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Monitor } from '@element-plus/icons-vue'
import type { Device } from '@/types'
import StatusBadge from './StatusBadge.vue'
import {
  getDeviceDisplayServiceStatus,
  getDeviceDisplayStatus,
  isDeviceCurrentlyOnline,
} from '@/utils/deviceStatus'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const props = defineProps<{
  device: Device
}>()

defineEmits<{
  click: []
}>()

const deviceStatus = computed(() => getDeviceDisplayStatus(props.device))
const isOnline = computed(() => isDeviceCurrentlyOnline(props.device))
const serviceStatus = computed(() => getDeviceDisplayServiceStatus(props.device))

const statusClass = computed(() => {
  return `status-${deviceStatus.value}`
})

const heartbeatText = computed(() => {
  if (!props.device.last_heartbeat) return '从未上线'
  return dayjs(props.device.last_heartbeat).fromNow()
})

const serviceStatusClass = computed(() => {
  return `service-${serviceStatus.value}`
})

const serviceStatusText = computed(() => {
  const map: Record<string, string> = {
    healthy: '健康',
    unhealthy: '异常',
    unknown: '未知'
  }
  return map[serviceStatus.value] || '未知'
})
</script>

<style scoped>
.device-card {
  cursor: pointer;
  transition: all 0.3s;
  width: 100%;
  height: 100%;
  min-height: 390px;
}

.device-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  box-sizing: border-box;
}

.device-card:hover {
  transform: translateY(-4px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-height: 44px;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.device-info > div {
  min-width: 0;
}

.device-icon {
  font-size: 36px;
}

.status-online {
  color: #67c23a;
}

.status-offline {
  color: #909399;
}

.status-waiting {
  color: #409eff;
}

.status-error {
  color: #f56c6c;
}

.status-deploying,
.status-updating {
  color: #e6a23c;
}

.device-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-id {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  min-height: 132px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  min-height: 22px;
}

.label {
  color: #909399;
  flex: 0 0 auto;
}

.value {
  color: #606266;
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
}

.resource-item {
  display: grid;
  grid-template-columns: 40px 1fr 50px;
  align-items: center;
  gap: 8px;
  height: 24px;
}

.resource-item :deep(.el-progress) {
  min-width: 0;
}

.resource-label {
  font-size: 12px;
  color: #909399;
}

.resource-value {
  font-size: 12px;
  color: #606266;
  text-align: right;
}

.resource-offline {
  font-size: 12px;
  color: #909399;
  line-height: 24px;
}

.resource-value-muted {
  color: #c0c4cc;
}

/* 服务状态指示器 */
.service-indicator {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  animation: pulse 2s infinite;
}

.service-healthy {
  background-color: #67c23a;
  box-shadow: 0 0 6px #67c23a;
}

.service-unhealthy {
  background-color: #f56c6c;
  box-shadow: 0 0 6px #f56c6c;
  animation: pulse-danger 1s infinite;
}

.service-unknown {
  background-color: #909399;
  box-shadow: none;
  animation: none;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}

@keyframes pulse-danger {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.2);
  }
}
</style>



