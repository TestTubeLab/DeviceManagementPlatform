<template>
  <div class="device-detail" v-loading="deviceStore.loading">
    <el-page-header @back="$router.back()">
      <template #content>
        <span class="page-title">设备详情</span>
      </template>
    </el-page-header>

    <div v-if="device" class="detail-content">
      <!-- 基本信息 -->
      <el-card shadow="hover" class="info-card">
        <template #header>
          <div class="card-header-content">
            <span class="card-title">基本信息</span>
            <div>
              <el-button type="primary" link :icon="Edit" @click="showEditDialog = true">编辑</el-button>
              <StatusBadge :status="device.status" style="margin-left: 12px" />
            </div>
          </div>
        </template>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="设备ID">{{ device.device_id }}</el-descriptions-item>
          <el-descriptions-item label="设备名称">
            <span v-if="device.name" style="font-weight: 600; color: #409EFF">{{ device.name }}</span>
            <span v-else style="color: #909399">未命名</span>
          </el-descriptions-item>
          <el-descriptions-item label="安装位置">{{ device.location || '-' }}</el-descriptions-item>
          <el-descriptions-item label="MAC地址">{{ device.mac_address || '-' }}</el-descriptions-item>
          <el-descriptions-item label="IP地址">{{ device.ip_address || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前版本">{{ device.current_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="设备分组">{{ device.group || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最后心跳">
            {{ device.last_heartbeat ? formatTime(device.last_heartbeat) : '从未上线' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(device.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatTime(device.updated_at) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
      
      <!-- 编辑设备信息对话框 -->
      <el-dialog v-model="showEditDialog" title="编辑设备信息" width="500px">
        <el-form :model="editForm" label-width="100px">
          <el-form-item label="设备ID">
            <el-input :value="device.device_id" disabled />
          </el-form-item>
          <el-form-item label="设备名称">
            <el-input v-model="editForm.name" placeholder="如：XX医院-流水线A-视觉服务器" />
          </el-form-item>
          <el-form-item label="安装位置">
            <el-input v-model="editForm.location" placeholder="如：3楼检验科" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" @click="handleSaveEdit" :loading="saving">保存</el-button>
        </template>
      </el-dialog>
      
      <!-- 自动部署配置 -->
      <el-card shadow="hover" class="info-card" style="margin-top: 20px">
        <template #header>
          <span class="card-title">自动部署配置</span>
        </template>
        <el-form label-width="120px">
          <el-form-item label="自动部署项目">
            <el-select
              v-model="autoDeployProject"
              placeholder="选择项目（设备上线时自动部署）"
              clearable
              filterable
              style="width: 100%"
              @change="handleAutoDeployChange"
            >
              <el-option
                v-for="project in projects"
                :key="project.id"
                :label="`${project.name} (${project.version})`"
                :value="project.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="设备分组">
            <el-input
              v-model="deviceGroup"
              placeholder="如：XX医院-流水线A"
              @blur="handleGroupChange"
            />
          </el-form-item>
          <el-alert
            title="提示：设置自动部署项目后，设备每次重启上线时会自动部署该项目"
            type="info"
            :closable="false"
            style="margin-top: 16px"
          />
        </el-form>
      </el-card>

      <!-- 资源使用情况 -->
      <el-row :gutter="20" style="margin-top: 20px">
        <el-col :span="8">
          <el-card shadow="hover">
            <template #header>
              <span class="card-title">CPU使用率</span>
            </template>
            <el-progress 
              type="dashboard" 
              :percentage="device.cpu_usage" 
              :color="getProgressColor(device.cpu_usage)"
            />
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover">
            <template #header>
              <span class="card-title">内存使用率</span>
            </template>
            <el-progress 
              type="dashboard" 
              :percentage="device.memory_usage"
              :color="getProgressColor(device.memory_usage)"
            />
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover">
            <template #header>
              <span class="card-title">磁盘使用率</span>
            </template>
            <el-progress 
              type="dashboard" 
              :percentage="device.disk_usage"
              :color="getProgressColor(device.disk_usage)"
            />
          </el-card>
        </el-col>
      </el-row>

      <!-- 操作按钮 -->
      <el-card shadow="hover" style="margin-top: 20px">
        <template #header>
          <span class="card-title">设备操作</span>
        </template>
        <el-space>
          <el-button type="primary" :icon="Refresh" @click="handleRestart">重启容器</el-button>
          <el-button type="success" :icon="Document" @click="handleViewLogs">查看日志</el-button>
          <el-button :icon="Setting" disabled title="配置管理功能开发中">配置管理</el-button>
          <el-button :icon="Delete" type="danger" @click="handleDelete">删除设备</el-button>
        </el-space>
        <el-alert
          title="提示：部署项目请前往「项目管理」页面操作"
          type="info"
          :closable="false"
          style="margin-top: 16px"
        />
      </el-card>
      
      <!-- 查看日志对话框 -->
      <el-dialog v-model="showLogsDialog" title="容器日志" width="900px" top="5vh">
        <div class="logs-container" v-loading="loadingLogs">
          <div class="logs-toolbar">
            <el-button size="small" :icon="Refresh" @click="refreshLogs">刷新</el-button>
            <el-tag size="small" type="info">最近100条日志（每分钟自动上报）</el-tag>
          </div>
          <div class="logs-content" ref="logsContentRef">
            <div
              v-for="(log, index) in containerLogs"
              :key="index"
              class="log-line"
              :class="getLogClass(log.level)"
            >
              <span class="log-time">{{ formatLogTime(log.timestamp) }}</span>
              <span class="log-level">[{{ log.level }}]</span>
              <span class="log-message">{{ log.message }}</span>
            </div>
            <el-empty v-if="containerLogs.length === 0 && !loadingLogs" description="暂无日志，请等待设备上报" />
          </div>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh, Setting, Delete, Edit, Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '@/stores/device'
import { restartDevice, deleteDevice, updateDevice, getContainerLogs } from '@/api/device'
import { getProjects } from '@/api/project'
import StatusBadge from '@/components/StatusBadge.vue'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const deviceStore = useDeviceStore()

const device = computed(() => deviceStore.currentDevice)
const projects = ref<any[]>([])
const autoDeployProject = ref<number | null>(null)
const deviceGroup = ref('')

// 编辑设备信息
const showEditDialog = ref(false)
const saving = ref(false)
const editForm = ref({
  name: '',
  location: ''
})

// 容器日志
const showLogsDialog = ref(false)
const loadingLogs = ref(false)
const containerLogs = ref<Array<{level: string, message: string, timestamp: string}>>([])
const logsContentRef = ref<HTMLElement | null>(null)

// 监听device变化，更新自动部署项目和分组
watch(device, (newDevice) => {
  if (newDevice) {
    autoDeployProject.value = newDevice.auto_deploy_project || null
    deviceGroup.value = newDevice.group || ''
    // 初始化编辑表单
    editForm.value.name = newDevice.name || ''
    editForm.value.location = newDevice.location || ''
  }
}, { immediate: true })

// 保存设备信息编辑
const handleSaveEdit = async () => {
  if (!device.value) return
  
  saving.value = true
  try {
    await updateDevice(device.value.device_id, {
      name: editForm.value.name,
      location: editForm.value.location
    })
    ElMessage.success('设备信息已更新')
    showEditDialog.value = false
    deviceStore.loadDevice(device.value.device_id)
  } catch (error) {
    ElMessage.error('更新失败')
  } finally {
    saving.value = false
  }
}

const formatTime = (time: string) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const formatLogTime = (time: string) => {
  return dayjs(time).format('HH:mm:ss')
}

const getProgressColor = (percentage: number) => {
  if (percentage < 60) return '#67c23a'
  if (percentage < 80) return '#e6a23c'
  return '#f56c6c'
}

const getLogClass = (level: string) => {
  return `log-${level.toLowerCase()}`
}

// 查看日志
const handleViewLogs = async () => {
  showLogsDialog.value = true
  await refreshLogs()
}

const refreshLogs = async () => {
  if (!device.value) return
  
  loadingLogs.value = true
  try {
    const data = await getContainerLogs(device.value.device_id)
    containerLogs.value = data.logs.reverse() // 倒序显示，最新的在最后
    
    // 滚动到底部
    setTimeout(() => {
      if (logsContentRef.value) {
        logsContentRef.value.scrollTop = logsContentRef.value.scrollHeight
      }
    }, 100)
  } catch (error) {
    ElMessage.error('获取日志失败')
  } finally {
    loadingLogs.value = false
  }
}

const handleRestart = async () => {
  if (!device.value) return
  
  try {
    await ElMessageBox.confirm(
      '确定要重启该设备的服务吗？',
      '重启确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    await restartDevice(device.value.device_id)
    ElMessage.success('重启任务已创建，设备将在下次心跳时执行重启')
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('重启任务创建失败')
    }
  }
}

const handleDelete = async () => {
  if (!device.value) return
  
  try {
    await ElMessageBox.confirm(
      `确定要删除设备 ${device.value.name || device.value.device_id} 吗？此操作不可恢复！`,
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      }
    )
    
    await deleteDevice(device.value.device_id)
    ElMessage.success('设备已删除')
    router.push('/devices')
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除设备失败')
    }
  }
}

const handleAutoDeployChange = async () => {
  if (!device.value) return
  
  try {
    await updateDevice(device.value.device_id, {
      auto_deploy_project: autoDeployProject.value
    })
    ElMessage.success('自动部署项目已设置')
    deviceStore.loadDevice(device.value.device_id)
  } catch (error) {
    ElMessage.error('设置失败')
  }
}

const handleGroupChange = async () => {
  if (!device.value) return
  
  try {
    await updateDevice(device.value.device_id, {
      group: deviceGroup.value
    })
    ElMessage.success('设备分组已更新')
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

const loadProjects = async () => {
  try {
    const data = await getProjects()
    projects.value = data.results
  } catch (error) {
    console.error('加载项目列表失败:', error)
  }
}

onMounted(() => {
  const deviceId = route.params.id as string
  deviceStore.loadDevice(deviceId)
  loadProjects()
})
</script>

<style scoped>
.device-detail {
  padding: 0;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.detail-content {
  margin-top: 20px;
}

.card-header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

/* 日志样式 */
.logs-container {
  height: 60vh;
  display: flex;
  flex-direction: column;
}

.logs-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.logs-content {
  flex: 1;
  overflow-y: auto;
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.log-line {
  display: flex;
  gap: 12px;
  padding: 2px 0;
  color: #d4d4d4;
}

.log-time {
  color: #6a9955;
  flex-shrink: 0;
}

.log-level {
  flex-shrink: 0;
  min-width: 70px;
}

.log-message {
  word-break: break-all;
}

.log-info .log-level {
  color: #569cd6;
}

.log-warning .log-level {
  color: #ce9178;
}

.log-error .log-level,
.log-error .log-message {
  color: #f14c4c;
}

.log-debug .log-level {
  color: #808080;
}
</style>


