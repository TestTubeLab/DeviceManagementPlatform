<template>
  <div class="task-manage">
    <h2 class="page-title">任务管理</h2>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>项目部署任务</span>
          <el-button type="primary" :icon="Refresh" @click="loadDeployments">刷新</el-button>
        </div>
      </template>

      <el-table :data="deployments" v-loading="loading" style="width: 100%">
        <el-table-column prop="id" label="任务ID" width="80" />
        <el-table-column label="项目" width="180">
          <template #default="{ row }">
            <span>{{ row.project_info?.name || '-' }}</span>
            <el-tag size="small" style="margin-left: 8px">{{ row.deployed_version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备" width="160">
          <template #default="{ row }">
            {{ row.device_info?.name || row.device_info?.device_id || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress 
              :percentage="row.progress" 
              :status="getProgressStatus(row.status)"
              :stroke-width="10"
            />
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" show-overflow-tooltip min-width="150" />
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && deployments.length === 0" description="暂无部署任务">
        <el-button type="primary" @click="$router.push('/projects')">
          前往项目管理
        </el-button>
      </el-empty>
    </el-card>

    <!-- 任务详情对话框 -->
    <el-dialog v-model="showDetailDialog" title="任务详情" width="600px">
      <el-descriptions v-if="currentDeployment" :column="1" border>
        <el-descriptions-item label="任务ID">{{ currentDeployment.id }}</el-descriptions-item>
        <el-descriptions-item label="项目">
          {{ currentDeployment.project_info?.name }}
        </el-descriptions-item>
        <el-descriptions-item label="设备">
          {{ currentDeployment.device_info?.name || currentDeployment.device_info?.device_id }}
        </el-descriptions-item>
        <el-descriptions-item label="目标版本">{{ currentDeployment.deployed_version }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(currentDeployment.status)">
            {{ getStatusText(currentDeployment.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="进度">
          <el-progress :percentage="currentDeployment.progress" />
        </el-descriptions-item>
        <el-descriptions-item label="消息">{{ currentDeployment.message || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误信息">
          <span v-if="currentDeployment.error_message" style="color: #f56c6c">
            {{ currentDeployment.error_message }}
          </span>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatTime(currentDeployment.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatTime(currentDeployment.updated_at) }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">
          {{ currentDeployment.completed_at ? formatTime(currentDeployment.completed_at) : '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getProjectDeployments, type ProjectDeployment } from '@/api/project'
import dayjs from 'dayjs'

const loading = ref(false)
const deployments = ref<ProjectDeployment[]>([])
const showDetailDialog = ref(false)
const currentDeployment = ref<ProjectDeployment | null>(null)

const loadDeployments = async () => {
  loading.value = true
  try {
    const res = await getProjectDeployments()
    deployments.value = res.results || []
  } catch (error) {
    console.error('加载部署任务失败:', error)
  } finally {
    loading.value = false
  }
}

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
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

const getStatusText = (status: string) => {
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

const getProgressStatus = (status: string) => {
  if (status === 'completed' || status === 'running') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

const formatTime = (time: string) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const viewDetail = (deployment: ProjectDeployment) => {
  currentDeployment.value = deployment
  showDetailDialog.value = true
}

onMounted(() => {
  loadDeployments()
  
  // 定时刷新（30秒）
  setInterval(loadDeployments, 30000)
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

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

