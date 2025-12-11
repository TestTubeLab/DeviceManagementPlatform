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
              <StatusBadge :status="device.computed_status || device.status" style="margin-left: 12px" />
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
          <el-descriptions-item label="项目版本">{{ device.current_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Agent版本">
            <span>{{ device.agent_version || 'unknown' }}</span>
            <el-button 
              v-if="device.is_online" 
              type="primary" 
              link 
              size="small" 
              style="margin-left: 8px"
              @click="handleUpdateAgent"
            >
              更新
            </el-button>
          </el-descriptions-item>
          <el-descriptions-item label="设备分组">{{ device.group || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最后心跳">
            <span v-if="device.last_heartbeat">
              {{ formatTime(device.last_heartbeat) }}
              <el-tag v-if="!device.is_online" type="danger" size="small" style="margin-left: 8px">
                已离线
              </el-tag>
            </span>
            <span v-else style="color: #909399">从未上线</span>
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
      
      <!-- 服务状态 -->
      <el-card shadow="hover" class="info-card" style="margin-top: 20px">
        <template #header>
          <div class="card-header-content">
            <span class="card-title">服务状态</span>
            <el-tag 
              :type="getServiceTagType(device.computed_service_status || device.service_status)" 
              size="large"
              effect="dark"
            >
              {{ getServiceStatusText(device.computed_service_status || device.service_status) }}
            </el-tag>
          </div>
        </template>
        <el-row :gutter="20">
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">容器状态</div>
              <div class="status-value">
                <el-tag :type="getContainerTagType(device.container_status)" size="small">
                  {{ getContainerStatusText(device.container_status) }}
                </el-tag>
              </div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">容器名称</div>
              <div class="status-value">{{ device.container_name || 'middleware' }}</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">运行时长</div>
              <div class="status-value">{{ device.container_uptime || '-' }}</div>
            </div>
          </el-col>
        </el-row>
        <el-row :gutter="20" style="margin-top: 16px">
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">响应时间</div>
              <div class="status-value">
                <span :class="getResponseTimeClass(device.service_response_time)">
                  {{ device.service_response_time }}ms
                </span>
              </div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">健康检查URL</div>
              <div class="status-value" style="font-size: 12px">{{ device.health_check_url || '-' }}</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="status-item">
              <div class="status-label">最后检查</div>
              <div class="status-value">{{ device.last_health_check ? formatTime(device.last_health_check) : '-' }}</div>
            </div>
          </el-col>
        </el-row>
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
          <el-button type="warning" :icon="FolderOpened" @click="showLogsDialog = true">日志中心</el-button>
          <el-button :icon="Setting" @click="showConfigDialog = true">配置管理</el-button>
          <el-button :icon="Delete" type="danger" @click="handleDelete">删除设备</el-button>
        </el-space>
        <el-alert
          title="提示：部署项目请前往「项目管理」页面操作"
          type="info"
          :closable="false"
          style="margin-top: 16px"
        />
      </el-card>
      
      <!-- 配置管理对话框 -->
      <el-dialog v-model="showConfigDialog" title="MiddlewareServer配置管理" width="900px" top="5vh">
        <el-tabs v-model="activeConfigTab">
          <el-tab-pane label="编辑配置" name="edit">
            <el-form :model="config" label-width="140px">
              <!-- 网段快捷设置 -->
              <el-divider content-position="left">
                <el-icon><Connection /></el-icon> 网络配置
              </el-divider>
              
              <el-form-item label="网段快捷设置">
                <el-input v-model="networkSegment" placeholder="192.168.31" style="width: 200px">
                  <template #append>
                    <el-button @click="applyNetworkSegment">应用到所有相机</el-button>
                  </template>
                </el-input>
                <el-text type="info" size="small" style="margin-left: 12px">
                  设置后自动生成：192.168.x.201-205
                </el-text>
              </el-form-item>
              
              <!-- 相机IP配置 -->
              <el-divider content-position="left">
                <el-icon><Camera /></el-icon> 相机IP配置
              </el-divider>
              
              <el-form-item 
                v-for="(cameraName, index) in cameraNames" 
                :key="cameraName" 
                :label="cameraName"
              >
                <el-input v-model="config.cameras[cameraName]" placeholder="192.168.31.201" style="width: 300px">
                  <template #prepend>{{ '.201 + ' + index }}</template>
                </el-input>
              </el-form-item>
              
              <!-- 上位机配置 -->
              <el-divider content-position="left">
                <el-icon><Connection /></el-icon> 上位机Socket配置
              </el-divider>
              
              <el-form-item label="上位机IP">
                <el-input v-model="config.plc.host" placeholder="192.168.31.29" style="width: 300px" />
              </el-form-item>
              
              <el-form-item label="Socket端口">
                <el-input-number v-model="config.plc.port" :min="1" :max="65535" />
              </el-form-item>
              
              <!-- 后端配置 -->
              <el-divider content-position="left">
                <el-icon><Monitor /></el-icon> 后端API配置
              </el-divider>
              
              <el-form-item label="后端地址">
                <el-input v-model="config.backend.host" placeholder="127.0.0.1" style="width: 300px" />
                <el-text type="info" size="small" style="margin-left: 12px">
                  通常为 127.0.0.1（容器内部）
                </el-text>
              </el-form-item>
              
              <el-form-item label="后端端口">
                <el-input-number v-model="config.backend.port" :min="1" :max="65535" />
              </el-form-item>
            </el-form>
            
            <div style="margin-top: 20px; text-align: center">
              <el-button @click="showConfigDialog = false">取消</el-button>
              <el-button type="primary" @click="handleSaveConfig" :loading="savingConfig">
                💾 保存并重启服务
              </el-button>
            </div>
            
            <el-alert
              title="保存后配置将立即应用，服务会自动重启（约15秒），期间服务不可用"
              type="warning"
              :closable="false"
              style="margin-top: 20px"
            />
          </el-tab-pane>
          
          <el-tab-pane label="配置历史" name="history">
            <div v-loading="loadingHistory">
              <el-timeline v-if="configHistory.length > 0">
                <el-timeline-item 
                  v-for="item in configHistory" 
                  :key="item.id"
                  :timestamp="formatTime(item.applied_at)" 
                  placement="top"
                  :type="item.status === 'success' ? 'success' : (item.status === 'failed' ? 'danger' : 'info')"
                >
                  <el-card>
                    <div style="display: flex; justify-content: space-between; align-items: center">
                      <div>
                        <el-tag 
                          :type="item.status === 'success' ? 'success' : (item.status === 'failed' ? 'danger' : 'info')"
                          size="large"
                        >
                          {{ item.status_display }}
                        </el-tag>
                        <el-tag type="info" size="small" style="margin-left: 8px" v-if="item.is_active">
                          当前生效
                        </el-tag>
                        <span style="margin-left: 12px; color: #606266">
                          操作人：{{ item.applied_by }}
                        </span>
                      </div>
                      <div>
                        <el-button link type="primary" @click="viewConfigDetail(item)">查看</el-button>
                        <el-button 
                          link 
                          type="warning" 
                          @click="handleRollback(item)"
                          :disabled="item.is_active"
                        >
                          回滚
                        </el-button>
                      </div>
                    </div>
                    <div v-if="item.error_message" style="margin-top: 8px">
                      <el-text type="danger" size="small">错误：{{ item.error_message }}</el-text>
                    </div>
                  </el-card>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-else description="暂无配置历史" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-dialog>
      
      <!-- 查看日志对话框 -->
      <el-dialog v-model="showLogsDialog" title="容器日志" width="900px" top="5vh">
        <div class="logs-container" v-loading="loadingLogs">
          <div class="logs-toolbar">
            <el-button size="small" :icon="Refresh" @click="refreshLogs">刷新</el-button>
            <el-select
              v-model="logLevelFilter"
              placeholder="筛选日志等级"
              clearable
              size="small"
              style="width: 160px; margin-left: 12px"
            >
              <el-option label="全部" value="" />
              <el-option label="🔴 CRITICAL" value="CRITICAL" />
              <el-option label="🔴 ERROR" value="ERROR" />
              <el-option label="🟡 WARNING" value="WARNING" />
              <el-option label="🔵 INFO" value="INFO" />
              <el-option label="🟢 DEBUG" value="DEBUG" />
            </el-select>
            <el-tag size="small" type="info" style="margin-left: 12px">
              显示 {{ filteredLogs.length }} / {{ containerLogs.length }} 条
            </el-tag>
          </div>
          <div class="logs-content" ref="logsContentRef">
            <div
              v-for="(log, index) in filteredLogs"
              :key="index"
              class="log-line"
              :class="getLogClass(log.level)"
            >
              <span class="log-time">{{ formatLogTime(log.timestamp) }}</span>
              <span class="log-level">[{{ log.level }}]</span>
              <span class="log-message">{{ log.message }}</span>
            </div>
            <el-empty v-if="filteredLogs.length === 0 && !loadingLogs" description="暂无日志，请等待设备上报" />
          </div>
        </div>
      </el-dialog>
      
      <!-- 日志中心对话框 -->
      <el-dialog 
        v-model="showLogsCenterDialog" 
        title="日志中心" 
        width="90%" 
        top="5vh"
        :close-on-click-modal="false"
      >
        <div class="logs-center">
          <!-- 左侧：日期和文件列表 -->
          <div class="logs-sidebar">
            <div class="sidebar-header">
              <el-button 
                type="primary" 
                :icon="Refresh" 
                @click="loadLogDates" 
                :loading="loadingDates"
                size="small"
              >
                刷新列表
              </el-button>
            </div>
            
            <el-scrollbar height="600px">
              <el-tree
                :data="logTree"
                :props="{ label: 'label', children: 'children' }"
                @node-click="handleLogNodeClick"
                :highlight-current="true"
                node-key="id"
              >
                <template #default="{ data }">
                  <span class="tree-node">
                    <el-icon v-if="data.type === 'date'"><Calendar /></el-icon>
                    <el-icon v-else><Document /></el-icon>
                    <span>{{ data.label }}</span>
                    <el-tag v-if="data.type === 'file' && data.special" type="warning" size="small">特殊</el-tag>
                  </span>
                </template>
              </el-tree>
            </el-scrollbar>
          </div>
          
          <!-- 右侧：日志内容 -->
          <div class="logs-main">
            <!-- 工具栏 -->
            <div class="logs-toolbar">
              <el-space>
                <!-- 搜索框 -->
                <el-input
                  v-model="logSearchKeyword"
                  placeholder="搜索关键词"
                  :prefix-icon="Search"
                  style="width: 200px"
                  clearable
                />
                
                <!-- 日志级别筛选 -->
                <el-select v-model="logLevelFilter" placeholder="日志级别" clearable style="width: 120px">
                  <el-option label="INFO" value="INFO" />
                  <el-option label="WARNING" value="WARNING" />
                  <el-option label="ERROR" value="ERROR" />
                  <el-option label="DEBUG" value="DEBUG" />
                  <el-option label="CRITICAL" value="CRITICAL" />
                </el-select>
                
                <!-- 搜索按钮 -->
                <el-button 
                  type="primary" 
                  :icon="Search" 
                  @click="handleSearchLogs"
                  :loading="searchingLogs"
                >
                  搜索
                </el-button>
              </el-space>
              
              <el-space>
                <!-- 行数限制 -->
                <el-input-number 
                  v-model="logLines" 
                  :min="0" 
                  :max="10000" 
                  :step="100"
                  controls-position="right"
                  style="width: 150px"
                />
                <span>行（0=全部）</span>
                
                <!-- 从尾部读取 -->
                <el-checkbox v-model="logTail">尾部读取</el-checkbox>
                
                <!-- 下载按钮 -->
                <el-button 
                  :icon="Download" 
                  @click="handleDownloadLog"
                  :disabled="!currentLogFile"
                >
                  下载
                </el-button>
              </el-space>
            </div>
            
            <!-- 日志内容显示 -->
            <div v-loading="loadingLogContent" class="logs-content-panel">
              <div v-if="!currentLogFile" class="empty-hint">
                <el-empty description="请从左侧选择日志文件" />
              </div>
              
              <div v-else-if="searchMode" class="search-results">
                <div class="search-info">
                  <span>搜索结果：找到 {{ searchResults.total_matches }} 条匹配</span>
                  <span v-if="searchResults.total_matches > searchResults.returned_matches">
                    （显示前 {{ searchResults.returned_matches }} 条）
                  </span>
                </div>
                
                <div 
                  v-for="(match, index) in searchResults.matches" 
                  :key="index"
                  class="search-result-item"
                >
                  <div class="result-meta">
                    <el-tag size="small">{{ match.date }}</el-tag>
                    <el-tag size="small" type="info">{{ match.file }}</el-tag>
                    <span class="line-num">Line {{ match.line_num }}</span>
                  </div>
                  <div class="result-content" v-html="highlightKeyword(match.content)"></div>
                </div>
              </div>
              
              <div v-else ref="logContentRef" class="logs-content">
                <div v-if="logContent" class="log-text">
                  <pre>{{ logContent }}</pre>
                </div>
                <el-empty v-else description="日志为空" />
              </div>
            </div>
            
            <!-- 底部信息栏 -->
            <div class="logs-footer">
              <span v-if="currentLogFile">
                当前文件：{{ currentLogDate }}/{{ currentLogFile }}
              </span>
              <span v-if="logTotalLines > 0">
                总行数：{{ logTotalLines }} | 显示：{{ logReturnedLines }} 行
              </span>
            </div>
          </div>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh, Setting, Delete, Edit, Document, Camera, Connection, Monitor, Calendar, Search, Download, FolderOpened } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '@/stores/device'
import { 
  restartDevice, deleteDevice, updateDevice, getContainerLogs, updateAgent,
  getCurrentConfig, applyConfig, getConfigHistory, rollbackConfig,
  listLogs, readLog, searchLogs, downloadLog, getLogTaskResult,
  type DeviceConfig, type ConfigHistory 
} from '@/api/device'
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
const logLevelFilter = ref('')
const filteredLogs = computed(() => {
  if (!logLevelFilter.value) {
    return containerLogs.value
  }
  return containerLogs.value.filter(log => log.level === logLevelFilter.value)
})

// 配置管理
const showConfigDialog = ref(false)
const activeConfigTab = ref('edit')
const savingConfig = ref(false)
const loadingHistory = ref(false)
const networkSegment = ref('192.168.31')
const cameraNames = ['样品盘', '前处理', '提取-纯化', '孔板传送', '反应体系构建']
const config = ref<DeviceConfig>({
  cameras: {
    '样品盘': '192.168.31.201',
    '前处理': '192.168.31.202',
    '提取-纯化': '192.168.31.203',
    '孔板传送': '192.168.31.204',
    '反应体系构建': '192.168.31.205'
  },
  plc: { host: '192.168.31.29', port: 9088 },
  backend: { host: '127.0.0.1', port: 8088 }
})
const configHistory = ref<ConfigHistory[]>([])

// 日志中心相关
const showLogsCenterDialog = ref(false)
const loadingDates = ref(false)
const loadingLogContent = ref(false)
const searchingLogs = ref(false)

// 日志树数据
const logTree = ref<any[]>([])
const currentLogDate = ref('')
const currentLogFile = ref('')

// 日志内容
const logContent = ref('')
const logTotalLines = ref(0)
const logReturnedLines = ref(0)

// 搜索相关
const logSearchKeyword = ref('')
const logLines = ref(500)
const logTail = ref(true)
const searchMode = ref(false)
const searchResults = ref<any>({ matches: [], total_matches: 0, returned_matches: 0 })

const logContentRef = ref<HTMLElement | null>(null)

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
  return dayjs(time).format('MM-DD HH:mm:ss')
}

const getProgressColor = (percentage: number) => {
  if (percentage < 60) return '#67c23a'
  if (percentage < 80) return '#e6a23c'
  return '#f56c6c'
}

// 服务状态相关
const getServiceTagType = (status: string) => {
  const map: Record<string, string> = {
    healthy: 'success',
    unhealthy: 'danger',
    unknown: 'info'
  }
  return map[status] || 'info'
}

const getServiceStatusText = (status: string) => {
  const map: Record<string, string> = {
    healthy: '服务健康',
    unhealthy: '服务异常',
    unknown: '状态未知'
  }
  return map[status] || '未知'
}

const getContainerTagType = (status: string) => {
  const map: Record<string, string> = {
    running: 'success',
    stopped: 'danger',
    not_found: 'warning',
    error: 'danger'
  }
  return map[status] || 'info'
}

const getContainerStatusText = (status: string) => {
  const map: Record<string, string> = {
    running: '运行中',
    stopped: '已停止',
    not_found: '未找到',
    error: '异常'
  }
  return map[status] || '未知'
}

const getResponseTimeClass = (time: number) => {
  if (time === 0) return 'response-unknown'
  if (time < 100) return 'response-fast'
  if (time < 500) return 'response-normal'
  return 'response-slow'
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

const handleUpdateAgent = async () => {
  if (!device.value) return
  
  try {
    await ElMessageBox.confirm(
      '确定要更新该设备的 Agent 吗？设备将在下次心跳时自动更新并重启 Agent 服务。',
      '更新 Agent',
      {
        confirmButtonText: '确定更新',
        cancelButtonText: '取消',
        type: 'info',
      }
    )
    
    await updateAgent(device.value.device_id)
    ElMessage.success('更新命令已发送，设备将在下次心跳时执行更新')
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('发送更新命令失败')
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

// ==================== 配置管理功能 ====================
// 应用网段到所有相机
const applyNetworkSegment = () => {
  const segment = networkSegment.value.trim()
  if (!segment) {
    ElMessage.warning('请输入网段')
    return
  }
  
  cameraNames.forEach((name, index) => {
    config.value.cameras[name] = `${segment}.${201 + index}`
  })
  
  // 同时更新上位机IP（通常在同一网段）
  config.value.plc.host = `${segment}.29`
  
  ElMessage.success('网段已应用到所有相机')
}

// 保存配置并重启服务
const handleSaveConfig = async () => {
  if (!device.value) return
  
  try {
    await ElMessageBox.confirm(
      '确定要应用新配置并重启服务吗？服务将短暂中断约15秒。',
      '确认操作',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    savingConfig.value = true
    
    // 应用配置
    const result = await applyConfig(device.value.device_id, config.value)
    ElMessage.success('配置已提交，设备正在应用...')
    
    showConfigDialog.value = false
    
    // 轮询检查配置应用状态
    pollConfigStatus(result.config_id)
    
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('配置应用失败')
    }
  } finally {
    savingConfig.value = false
  }
}

// 轮询配置应用状态
const pollConfigStatus = (configId: number) => {
  const maxAttempts = 20  // 最多检查20次（20秒）
  let attempts = 0
  
  const timer = setInterval(async () => {
    attempts++
    
    try {
      const history = await getConfigHistory(device.value!.device_id)
      const latest = history.find(h => h.id === configId)
      
      if (latest && latest.status !== 'pending') {
        clearInterval(timer)
        
        if (latest.status === 'success') {
          ElMessage.success('✅ 配置应用成功，服务已重启')
          // 刷新配置历史
          await loadConfigHistory()
        } else {
          ElMessage.error(`❌ 配置应用失败: ${latest.error_message}`)
        }
      } else if (attempts >= maxAttempts) {
        clearInterval(timer)
        ElMessage.warning('配置应用超时，请查看配置历史确认状态')
      }
    } catch (error) {
      console.error('检查配置状态失败:', error)
    }
  }, 2000)  // 每2秒检查一次
}

// 加载配置历史
const loadConfigHistory = async () => {
  if (!device.value) return
  
  loadingHistory.value = true
  try {
    configHistory.value = await getConfigHistory(device.value.device_id)
  } catch (error) {
    ElMessage.error('加载配置历史失败')
  } finally {
    loadingHistory.value = false
  }
}

// 查看配置详情
const viewConfigDetail = (item: ConfigHistory) => {
  ElMessageBox.alert(
    `<pre style="max-height: 400px; overflow: auto">${JSON.stringify(item.config_data, null, 2)}</pre>`,
    '配置详情',
    {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭'
    }
  )
}

// 回滚配置
const handleRollback = async (item: ConfigHistory) => {
  if (!device.value) return
  
  try {
    await ElMessageBox.confirm(
      `确定要回滚到 ${dayjs(item.applied_at).format('YYYY-MM-DD HH:mm:ss')} 的配置吗？`,
      '回滚确认',
      {
        confirmButtonText: '确定回滚',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    loadingHistory.value = true
    const result = await rollbackConfig(device.value.device_id, item.id)
    ElMessage.success('配置回滚已提交')
    
    // 轮询状态
    pollConfigStatus(result.config_id)
    
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('配置回滚失败')
    }
  } finally {
    loadingHistory.value = false
  }
}

// 监听配置对话框打开，加载当前配置和历史
watch(showConfigDialog, async (newVal) => {
  if (newVal && device.value) {
    // 加载当前配置
    try {
      const currentConfig = await getCurrentConfig(device.value.device_id)
      config.value = currentConfig
      
      // 从相机IP推断网段
      const firstCameraIp = Object.values(currentConfig.cameras)[0]
      if (firstCameraIp) {
        const parts = firstCameraIp.split('.')
        if (parts.length === 4) {
          networkSegment.value = `${parts[0]}.${parts[1]}.${parts[2]}`
        }
      }
    } catch (error) {
      console.error('加载当前配置失败:', error)
    }
    
    // 加载配置历史
    await loadConfigHistory()
  }
})

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

let refreshTimer: NodeJS.Timeout | null = null

onMounted(() => {
  const deviceId = route.params.id as string
  deviceStore.loadDevice(deviceId)
  loadProjects()
  
  // 自动刷新设备状态（每5秒，静默刷新不显示loading，匹配Agent心跳间隔）
  refreshTimer = setInterval(() => {
    deviceStore.refreshDevice(deviceId)
  }, 5000)
})

onUnmounted(() => {
  // 清除定时器
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

// ==================== 日志中心功能 ====================

// 加载日志日期列表
const loadLogDates = async () => {
  if (!device.value) return
  
  loadingDates.value = true
  try {
    // 创建列表任务
    const { task_id } = await listLogs(device.value.device_id)
    
    // 轮询任务结果
    const result = await pollTaskResult(task_id)
    
    if (result.status === 'completed') {
      const { dates, files } = result.result
      
      // 构建树形结构
      logTree.value = dates.map((date: string) => ({
        id: `date_${date}`,
        label: date,
        type: 'date',
        children: files[date]?.map((file: string) => ({
          id: `file_${date}_${file}`,
          label: file,
          type: 'file',
          date: date,
          file: file,
          special: file === 'FileCleaner.log' || file === '00h00m.log'
        })) || []
      }))
      
      ElMessage.success('日志列表加载成功')
    } else {
      ElMessage.error(result.error_message || '加载日志列表失败')
    }
  } catch (error) {
    ElMessage.error('加载日志列表失败')
  } finally {
    loadingDates.value = false
  }
}

// 点击树节点
const handleLogNodeClick = async (data: any) => {
  if (data.type === 'file') {
    await loadLogContent(data.date, data.file)
  }
}

// 加载日志内容
const loadLogContent = async (date: string, file: string) => {
  if (!device.value) return
  
  searchMode.value = false
  currentLogDate.value = date
  currentLogFile.value = file
  loadingLogContent.value = true
  
  try {
    const { task_id } = await readLog(device.value.device_id, {
      date,
      file,
      lines: logLines.value,
      tail: logTail.value
    })
    
    const result = await pollTaskResult(task_id)
    
    if (result.status === 'completed') {
      logContent.value = result.result.content
      logTotalLines.value = result.result.total_lines
      logReturnedLines.value = result.result.returned_lines
      
      // 滚动到底部（如果是tail模式）
      if (logTail.value) {
        setTimeout(() => {
          if (logContentRef.value) {
            logContentRef.value.scrollTop = logContentRef.value.scrollHeight
          }
        }, 100)
      }
    } else {
      ElMessage.error(result.error_message || '读取日志失败')
    }
  } catch (error) {
    ElMessage.error('读取日志失败')
  } finally {
    loadingLogContent.value = false
  }
}

// 搜索日志
const handleSearchLogs = async () => {
  if (!device.value || !logSearchKeyword.value) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  
  searchMode.value = true
  searchingLogs.value = true
  
  try {
    const { task_id } = await searchLogs(device.value.device_id, {
      keyword: logSearchKeyword.value,
      level: logLevelFilter.value,
      case_sensitive: false
    })
    
    const result = await pollTaskResult(task_id)
    
    if (result.status === 'completed') {
      searchResults.value = result.result
      ElMessage.success(`找到 ${result.result.total_matches} 条匹配`)
    } else {
      ElMessage.error(result.error_message || '搜索失败')
    }
  } catch (error) {
    ElMessage.error('搜索失败')
  } finally {
    searchingLogs.value = false
  }
}

// 下载日志
const handleDownloadLog = async () => {
  if (!device.value || !currentLogDate.value || !currentLogFile.value) return
  
  try {
    const { task_id } = await downloadLog(device.value.device_id, {
      date: currentLogDate.value,
      files: [currentLogFile.value]
    })
    
    ElMessage.info('正在准备下载...')
    
    const result = await pollTaskResult(task_id, 30000)  // 30秒超时
    
    if (result.status === 'completed') {
      // Base64解码并下载
      const { content, filename } = result.result
      const binaryString = atob(content)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }
      const blob = new Blob([bytes], { type: 'application/zip' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      
      ElMessage.success('下载成功')
    } else {
      ElMessage.error(result.error_message || '下载失败')
    }
  } catch (error) {
    ElMessage.error('下载失败')
  }
}

// 轮询任务结果（通用函数）
const pollTaskResult = async (taskId: number, timeout: number = 10000): Promise<any> => {
  if (!device.value) throw new Error('设备不存在')
  
  const startTime = Date.now()
  
  while (Date.now() - startTime < timeout) {
    const result = await getLogTaskResult(device.value.device_id, taskId)
    
    if (result.status === 'completed' || result.status === 'failed') {
      return result
    }
    
    // 等待1秒后重试
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  
  throw new Error('任务超时')
}

// 高亮关键词
const highlightKeyword = (text: string) => {
  if (!logSearchKeyword.value) return text
  const regex = new RegExp(`(${logSearchKeyword.value})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

// 监听对话框打开
watch(showLogsCenterDialog, (newVal) => {
  if (newVal && logTree.value.length === 0) {
    loadLogDates()
  }
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

/* 服务状态样式 */
.status-item {
  text-align: center;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 8px;
}

.status-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.status-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.response-fast {
  color: #67c23a;
}

.response-normal {
  color: #e6a23c;
}

.response-slow {
  color: #f56c6c;
}

.response-unknown {
  color: #909399;
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

/* 日志中心样式 */
.logs-center {
  display: flex;
  gap: 16px;
  height: 650px;
}

.logs-sidebar {
  width: 280px;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 12px;
  border-bottom: 1px solid #e4e7ed;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.logs-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.logs-content-panel {
  flex: 1;
  overflow: hidden;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #1e1e1e;
}

.logs-content {
  height: 100%;
  overflow: auto;
  padding: 16px;
}

.log-text {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #d4d4d4;
}

.log-text pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.empty-hint {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-results {
  height: 100%;
  overflow: auto;
  padding: 16px;
}

.search-info {
  color: #67c23a;
  margin-bottom: 12px;
  font-size: 14px;
}

.search-result-item {
  margin-bottom: 16px;
  padding: 12px;
  background: #2d2d2d;
  border-radius: 4px;
  border-left: 3px solid #409eff;
}

.result-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}

.line-num {
  color: #909399;
  font-size: 12px;
}

.result-content {
  color: #d4d4d4;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.result-content mark {
  background-color: #f56c6c;
  color: #fff;
  padding: 2px 4px;
  border-radius: 2px;
}

.logs-footer {
  margin-top: 12px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
  display: flex;
  justify-content: space-between;
}
</style>


