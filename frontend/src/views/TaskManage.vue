<template>
  <div class="task-manage">
    <h2 class="page-title">任务管理</h2>

    <el-tabs v-model="activeTab">
      <!-- 部署任务 -->
      <el-tab-pane label="部署任务" name="deployment">
        <el-table :data="taskStore.deploymentTasks" v-loading="taskStore.loading">
          <el-table-column prop="id" label="任务ID" width="80" />
          <el-table-column label="设备" width="200">
            <template #default="{ row }">
              {{ getDeviceName(row.device) }}
            </template>
          </el-table-column>
          <el-table-column prop="target_version" label="目标版本" width="120" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="getDeployStatusType(row.status)">
                {{ getDeployStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="200">
            <template #default="{ row }">
              <el-progress :percentage="row.progress" :status="getProgressStatus(row.status)" />
            </template>
          </el-table-column>
          <el-table-column prop="message" label="消息" show-overflow-tooltip />
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">
              {{ formatTime(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button 
                link 
                type="primary" 
                size="small"
                @click="viewTaskDetail(row)"
              >
                详情
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 更新任务 -->
      <el-tab-pane label="更新任务" name="update">
        <el-table :data="taskStore.updateTasks" v-loading="taskStore.loading">
          <el-table-column prop="id" label="任务ID" width="80" />
          <el-table-column label="设备" width="200">
            <template #default="{ row }">
              {{ getDeviceName(row.device) }}
            </template>
          </el-table-column>
          <el-table-column prop="from_version" label="原版本" width="120" />
          <el-table-column prop="target_version" label="目标版本" width="120" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="getUpdateStatusType(row.status)">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="200">
            <template #default="{ row }">
              <el-progress :percentage="row.progress" :status="getProgressStatus(row.status)" />
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">
              {{ formatTime(row.created_at) }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 任务详情对话框 -->
    <el-dialog v-model="showDetailDialog" title="任务详情" width="600px">
      <el-descriptions v-if="currentTask" :column="1" border>
        <el-descriptions-item label="任务ID">{{ currentTask.id }}</el-descriptions-item>
        <el-descriptions-item label="设备">{{ getDeviceName(currentTask.device) }}</el-descriptions-item>
        <el-descriptions-item label="目标版本">{{ currentTask.target_version }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getDeployStatusType(currentTask.status)">
            {{ getDeployStatusText(currentTask.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="进度">
          <el-progress :percentage="currentTask.progress" />
        </el-descriptions-item>
        <el-descriptions-item label="消息">{{ currentTask.message || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误信息">{{ currentTask.error_message || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatTime(currentTask.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatTime(currentTask.updated_at) }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">
          {{ currentTask.completed_at ? formatTime(currentTask.completed_at) : '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useDeviceStore } from '@/stores/device'
import { useTaskStore } from '@/stores/task'
import type { DeploymentTask } from '@/types'
import dayjs from 'dayjs'

const deviceStore = useDeviceStore()
const taskStore = useTaskStore()

const activeTab = ref('deployment')
const showDetailDialog = ref(false)
const currentTask = ref<DeploymentTask | null>(null)

const getDeviceName = (deviceId: number) => {
  const device = deviceStore.devices.find(d => d.id === deviceId)
  return device?.name || device?.device_id || `设备 ${deviceId}`
}

const getDeployStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    downloading: 'warning',
    configuring: 'warning',
    starting: 'warning',
    checking: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return typeMap[status] || 'info'
}

const getDeployStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    pending: '等待中',
    downloading: '下载中',
    configuring: '配置中',
    starting: '启动中',
    checking: '检查中',
    completed: '已完成',
    failed: '失败',
  }
  return textMap[status] || status
}

const getUpdateStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    downloading: 'warning',
    installing: 'warning',
    success: 'success',
    failed: 'danger',
    rolled_back: 'warning',
  }
  return typeMap[status] || 'info'
}

const getProgressStatus = (status: string) => {
  if (status === 'completed' || status === 'success') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

const formatTime = (time: string) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const viewTaskDetail = (task: DeploymentTask) => {
  currentTask.value = task
  showDetailDialog.value = true
}

onMounted(() => {
  deviceStore.loadDevices()
  taskStore.loadDeploymentTasks()
  taskStore.loadUpdateTasks()
})
</script>

<style scoped>
.task-manage {
  padding: 0;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}
</style>


