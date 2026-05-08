<template>
  <div class="dashboard">
    <h2 class="page-title">监控仪表盘</h2>
    
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon online">
            <el-icon><Check /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ deviceStore.onlineCount() }}</div>
            <div class="stat-label">在线设备</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon offline">
            <el-icon><Close /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ deviceStore.offlineCount() }}</div>
            <div class="stat-label">离线设备</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon waiting">
            <el-icon><Clock /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ deviceStore.waitingCount() }}</div>
            <div class="stat-label">待部署设备</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon tasks">
            <el-icon><List /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ pendingTaskCount }}</div>
            <div class="stat-label">进行中任务</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 设备状态分布 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">设备状态分布</span>
          </template>
          <div ref="statusChart" style="height: 300px"></div>
        </el-card>
      </el-col>
      
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">最近上线设备</span>
          </template>
          <el-table :data="recentDevices" max-height="300">
            <el-table-column prop="device_id" label="设备ID" width="180" />
            <el-table-column prop="ip_address" label="IP地址" width="140" />
            <el-table-column label="状态">
              <template #default="{ row }">
                <StatusBadge :status="getDeviceDisplayStatus(row)" />
              </template>
            </el-table-column>
            <el-table-column label="最后心跳">
              <template #default="{ row }">
                {{ formatTime(row.last_heartbeat) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近部署任务 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="card-title">最近部署任务</span>
              <el-button type="primary" link @click="$router.push('/tasks')">查看全部</el-button>
            </div>
          </template>
          <el-table :data="recentDeployments" max-height="300">
            <el-table-column prop="id" label="任务ID" width="80" />
            <el-table-column label="项目" width="180">
              <template #default="{ row }">
                {{ row.project_info?.name || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="设备" width="160">
              <template #default="{ row }">
                {{ row.device_info?.name || row.device_info?.device_id || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">
                  {{ getStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="150">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :status="getProgressStatus(row.status)" :stroke-width="8" />
              </template>
            </el-table-column>
            <el-table-column prop="message" label="消息" show-overflow-tooltip />
            <el-table-column label="创建时间" width="160">
              <template #default="{ row }">
                {{ formatTime(row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="recentDeployments.length === 0" description="暂无部署任务" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { Check, Close, Clock, List } from '@element-plus/icons-vue'
import { useDeviceStore } from '@/stores/device'
import { getProjectDeployments, type ProjectDeployment } from '@/api/project'
import StatusBadge from '@/components/StatusBadge.vue'
import { getDeviceDisplayStatus, isDeviceCurrentlyOnline } from '@/utils/deviceStatus'
import {
  ACTIVE_PROJECT_DEPLOYMENT_STATUS_QUERY,
  getProjectDeploymentProgressStatus,
  getProjectDeploymentStatusText,
  getProjectDeploymentStatusType,
} from '@/utils/projectDeploymentStatus'
import * as echarts from 'echarts'
import dayjs from 'dayjs'

const deviceStore = useDeviceStore()

const statusChart = ref<HTMLElement>()
const recentDeployments = ref<ProjectDeployment[]>([])
const activeDeploymentCount = ref(0)

const getHeartbeatValue = (time: string | null) => {
  if (!time) return 0
  return dayjs(time).valueOf()
}

const recentDevices = computed(() => {
  return [...deviceStore.devices]
    .filter(device => isDeviceCurrentlyOnline(device))
    .sort((a, b) => getHeartbeatValue(b.last_heartbeat) - getHeartbeatValue(a.last_heartbeat))
    .slice(0, 5)
})

const pendingTaskCount = computed(() => {
  return activeDeploymentCount.value
})

const getStatusType = (status: string) => {
  return getProjectDeploymentStatusType(status)
}

const getStatusText = (status: string) => {
  return getProjectDeploymentStatusText(status)
}

const getProgressStatus = (status: string) => {
  return getProjectDeploymentProgressStatus(status)
}

const formatTime = (time: string | null) => {
  if (!time) return '-'
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const initStatusChart = () => {
  if (!statusChart.value) return
  
  const chart = echarts.getInstanceByDom(statusChart.value) || echarts.init(statusChart.value)
  
  const statusLabels: Record<string, string> = {
    online: '在线',
    offline: '离线',
    waiting: '待部署',
    deploying: '部署中',
    updating: '更新中',
    error: '异常'
  }
  
  const statusColors: Record<string, string> = {
    online: '#67c23a',
    offline: '#909399',
    waiting: '#409eff',
    deploying: '#e6a23c',
    updating: '#36cfc9',
    error: '#f56c6c'
  }
  
  const statusCount: Record<string, number> = {}
  deviceStore.devices.forEach(device => {
    const status = getDeviceDisplayStatus(device)
    statusCount[status] = (statusCount[status] || 0) + 1
  })
  
  const option = {
    tooltip: {
      trigger: 'item'
    },
    legend: {
      orient: 'vertical',
      left: 'left'
    },
    series: [
      {
        name: '设备状态',
        type: 'pie',
        radius: '60%',
        data: Object.entries(statusCount).map(([status, value]) => ({
          name: statusLabels[status] || status,
          value: value,
          itemStyle: {
            color: statusColors[status] || '#909399'
          }
        })),
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowOffsetX: 0,
            shadowColor: 'rgba(0, 0, 0, 0.5)'
          }
        }
      }
    ]
  }
  
  chart.setOption(option)
}

const loadDeployments = async () => {
  try {
    const [recentRes, activeRes] = await Promise.all([
      getProjectDeployments(),
      getProjectDeployments({ status: ACTIVE_PROJECT_DEPLOYMENT_STATUS_QUERY }),
    ])
    recentDeployments.value = (recentRes.results || []).slice(0, 10)
    activeDeploymentCount.value = activeRes.count ?? (activeRes.results || []).length
  } catch (error) {
    console.error('加载部署任务失败:', error)
  }
}

const loadData = async () => {
  await Promise.all([
    deviceStore.loadDevices(),
    loadDeployments()
  ])
  initStatusChart()
}

let refreshTimer: number

onMounted(() => {
  loadData()
  // 每30秒刷新一次
  refreshTimer = setInterval(loadData, 30000)
})

onUnmounted(() => {
  clearInterval(refreshTimer)
})
</script>

<style scoped>
.dashboard {
  padding: 0;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  padding: 20px;
}

.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  margin-right: 16px;
}

.stat-icon.online {
  background: #f0f9ff;
  color: #67c23a;
}

.stat-icon.offline {
  background: #f4f4f5;
  color: #909399;
}

.stat-icon.waiting {
  background: #ecf5ff;
  color: #409eff;
}

.stat-icon.tasks {
  background: #fef0f0;
  color: #e6a23c;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

