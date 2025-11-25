<template>
  <el-tag :type="tagType" size="small">
    {{ statusText }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DeviceStatus } from '@/types'

const props = defineProps<{
  status: DeviceStatus
}>()

const statusMap: Record<DeviceStatus, { type: '' | 'success' | 'warning' | 'danger' | 'info', text: string }> = {
  waiting: { type: 'info', text: '等待部署' },
  deploying: { type: 'warning', text: '部署中' },
  online: { type: 'success', text: '在线' },
  offline: { type: 'info', text: '离线' },
  updating: { type: 'warning', text: '更新中' },
  error: { type: 'danger', text: '异常' },
}

const tagType = computed(() => statusMap[props.status]?.type || 'info')
const statusText = computed(() => statusMap[props.status]?.text || props.status)
</script>


