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
            <div class="stat-value">{{ taskStore.pendingTasksCount() }}</div>
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
                <StatusBadge :status="row.status" />
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

    <!-- 最近任务 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">最近任务</span>
          </template>
          <el-table :data="recentTasks" max-height="300">
            <el-table-column prop="id" label="任务ID" width="80" />
            <el-table-column label="设备" width="180">
              <template #default="{ row }">
                {{ getDeviceName(row.device) }}
              </template>
            </el-table-column>
            <el-table-column prop="target_version" label="目标版本" width="120" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="getTaskStatusType(row.status)">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="200">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" />
              </template>
            </el-table-column>
            <el-table-column prop="message" label="消息" show-overflow-tooltip />
            <el-table-column label="创建时间" width="160">
              <template #default="{ row }">
                {{ formatTime(row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { Check, Close, Clock, List } from '@element-plus/icons-vue'
import { useDeviceStore } from '@/stores/device'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'

const deviceStore = useDeviceStore()
const taskStore = useTaskStore()

const statusChart = ref<HTMLElement>()

const recentDevices = computed(() => {
  return deviceStore.devices.slice(0, 5)
})

const recentTasks = computed(() => {
  return taskStore.deploymentTasks.slice(0, 10)
})

const getDeviceName = (deviceId: number) => {
  const device = deviceStore.devices.find(d => d.id === deviceId)
  return device?.name || device?.device_id || `设备 ${deviceId}`
}

const getTaskStatusType = (status: string) => {
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

const formatTime = (time: string | null) => {
  if (!time) return '-'
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const initStatusChart = () => {
  if (!statusChart.value) return
  
  const chart = echarts.init(statusChart.value)
  
  const statusCount: Record<string, number> = {}
  deviceStore.devices.forEach(device => {
    statusCount[device.status] = (statusCount[device.status] || 0) + 1
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
        data: Object.entries(statusCount).map(([name, value]) => ({
          name: name,
          value: value
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

const loadData = async () => {
  await Promise.all([
    deviceStore.loadDevices(),
    taskStore.loadDeploymentTasks(),
    taskStore.loadUpdateTasks(),
  ])
  initStatusChart()
}

onMounted(() => {
  loadData()
  
  // 每30秒刷新一次
  setInterval(loadData, 30000)
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
</style>


