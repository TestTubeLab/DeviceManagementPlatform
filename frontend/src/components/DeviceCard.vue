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
      <StatusBadge :status="device.status" />
    </div>
    
    <el-divider style="margin: 12px 0" />
    
    <div class="card-body">
      <div class="info-row">
        <span class="label">IP地址:</span>
        <span class="value">{{ device.ip_address || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="label">版本:</span>
        <span class="value">{{ device.current_version || '-' }}</span>
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
        <el-progress :percentage="device.cpu_usage" :stroke-width="6" :show-text="false" />
        <span class="resource-value">{{ device.cpu_usage.toFixed(1) }}%</span>
      </div>
      <div class="resource-item">
        <span class="resource-label">内存</span>
        <el-progress :percentage="device.memory_usage" :stroke-width="6" :show-text="false" />
        <span class="resource-value">{{ device.memory_usage.toFixed(1) }}%</span>
      </div>
      <div class="resource-item">
        <span class="resource-label">磁盘</span>
        <el-progress :percentage="device.disk_usage" :stroke-width="6" :show-text="false" />
        <span class="resource-value">{{ device.disk_usage.toFixed(1) }}%</span>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Monitor } from '@element-plus/icons-vue'
import type { Device } from '@/types'
import StatusBadge from './StatusBadge.vue'
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

const statusClass = computed(() => {
  return `status-${props.device.status}`
})

const heartbeatText = computed(() => {
  if (!props.device.last_heartbeat) return '从未上线'
  return dayjs(props.device.last_heartbeat).fromNow()
})
</script>

<style scoped>
.device-card {
  cursor: pointer;
  transition: all 0.3s;
}

.device-card:hover {
  transform: translateY(-4px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.device-info {
  display: flex;
  align-items: center;
  gap: 12px;
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
}

.device-id {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.label {
  color: #909399;
}

.value {
  color: #606266;
  font-weight: 500;
}

.card-footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.resource-item {
  display: grid;
  grid-template-columns: 40px 1fr 50px;
  align-items: center;
  gap: 8px;
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
</style>


