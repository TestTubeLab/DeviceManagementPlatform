<template>
  <div class="frp-manage">
    <div class="page-header">
      <div>
        <h2 class="page-title">FRP管理</h2>
        <p class="page-subtitle">集中管理 FRP 服务状态、端口范围和设备启用关系</p>
      </div>
      <el-button :icon="Refresh" @click="loadOverview">刷新</el-button>
    </div>

    <el-row :gutter="20" class="summary-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="summary-card">
          <div class="summary-label">服务状态</div>
          <div class="summary-value">
            <el-tag :type="getServiceTagType(overview?.service.status)" size="large">
              {{ getServiceStatusText(overview?.service.status) }}
            </el-tag>
          </div>
          <div class="summary-help">{{ overview?.service.container_name || 'frps-service' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="summary-card">
          <div class="summary-label">平台配置</div>
          <div class="summary-value">
            <el-tag :type="configForm.is_active ? 'success' : 'info'" size="large">
              {{ configForm.is_active ? '已启用' : '已停用' }}
            </el-tag>
          </div>
          <div class="summary-help">配置版本 {{ overview?.config.config_version ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="summary-card">
          <div class="summary-label">端口池</div>
          <div class="summary-value monospace">
            {{ configForm.port_pool_start || '-' }} - {{ configForm.port_pool_end || '-' }}
          </div>
          <div class="summary-help">
            已用 {{ overview?.config.used_ports_count ?? 0 }} / {{ overview?.config.total_ports ?? 0 }}
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="summary-card">
          <div class="summary-label">已启用设备</div>
          <div class="summary-value">{{ overview?.config.enabled_devices_count ?? 0 }}</div>
          <div class="summary-help">已连接 {{ overview?.config.connected_devices_count ?? 0 }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="main-row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="hover" v-loading="loading">
          <template #header>
            <div class="card-header">
              <span>FRP配置</span>
              <el-space>
                <el-button :icon="RefreshRight" @click="handleSync">重新同步配置</el-button>
                <el-button type="primary" :loading="savingConfig" @click="handleSaveConfig">保存并应用</el-button>
              </el-space>
            </div>
          </template>

          <el-alert
            :title="configForm.is_active ? '保存后会同步到 frps 服务配置，并在服务运行中自动重启生效。' : '当前已停用平台侧 FRP，下次设备心跳时会收到停用指令。'"
            :type="configForm.is_active ? 'info' : 'warning'"
            :closable="false"
            class="config-alert"
          />

          <el-form :model="configForm" label-width="120px">
            <el-row :gutter="20">
              <el-col :xs="24" :md="12">
                <el-form-item label="服务器地址">
                  <el-input v-model="configForm.server_addr" placeholder="212.64.81.95" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="服务端口">
                  <el-input-number v-model="configForm.server_port" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :xs="24" :md="12">
                <el-form-item label="端口池起始">
                  <el-input-number v-model="configForm.port_pool_start" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="端口池结束">
                  <el-input-number v-model="configForm.port_pool_end" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item>
              <span class="form-hint">每台设备固定占用两个相邻端口：SSH 使用 N，Web 访问使用 N + 1（设备本机 8088）。</span>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :xs="24" :md="12">
                <el-form-item label="访问令牌">
                  <el-input v-model="configForm.token" show-password placeholder="请输入 token" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="平台FRP">
                  <el-switch v-model="configForm.is_active" active-text="启用" inactive-text="停用" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="备注">
              <el-input v-model="configForm.description" type="textarea" :rows="3" placeholder="可选备注" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="hover" v-loading="serviceActionLoading">
          <template #header>
            <div class="card-header">
              <span>FRP服务控制</span>
              <el-tag :type="getServiceTagType(overview?.service.status)">
                {{ getServiceStatusText(overview?.service.status) }}
              </el-tag>
            </div>
          </template>

          <el-descriptions :column="1" border class="service-desc">
            <el-descriptions-item label="容器名称">
              <span class="monospace">{{ overview?.service.container_name || 'frps-service' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="当前状态">
              {{ getServiceStatusText(overview?.service.status) }}
            </el-descriptions-item>
            <el-descriptions-item label="最近启动">
              {{ formatStartedAt(overview?.service.started_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="错误信息">
              {{ overview?.service.error || '-' }}
            </el-descriptions-item>
          </el-descriptions>

          <el-space wrap class="service-actions">
            <el-button type="success" :icon="VideoPlay" @click="handleServiceAction('start')">启动</el-button>
            <el-button type="warning" :icon="VideoPause" @click="handleServiceAction('stop')">停止</el-button>
            <el-button type="primary" :icon="RefreshRight" @click="handleServiceAction('restart')">重启</el-button>
          </el-space>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" class="devices-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>设备 FRP 分配</span>
          <el-input
            v-model="searchText"
            placeholder="搜索设备ID、名称或IP"
            clearable
            class="device-search"
          />
        </div>
      </template>

      <el-alert v-if="overview?.firewall.state !== 'applied'" class="firewall-alert"
        :type="getFirewallAlertType(overview?.firewall.state)" :closable="false"
        :title="getFirewallAlertText(overview?.firewall)" />
      <el-alert class="access-hint" type="info" :closable="false"
        title="关闭公网直连不会关闭 FRP 隧道；仍可通过 jetson_remote 经 212 回环转发管理设备。" />

      <el-table :data="filteredDevices" border>
        <el-table-column label="设备" min-width="220">
          <template #default="{ row }">
            <div class="device-name-cell">
              <div class="device-name">{{ row.name || row.device_id }}</div>
              <div class="device-sub">{{ row.device_id }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP地址" min-width="140" />
        <el-table-column label="设备状态" min-width="120">
          <template #default="{ row }">
            <el-tag :type="getDeviceStatusTagType(row.computed_status || row.status)">
              {{ getDeviceStatusText(row.computed_status || row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="FRP启用" min-width="120">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.frp_enabled"
              :loading="deviceLoadingId === row.device_id"
              @change="(value) => handleToggleDeviceFrp(row.device_id, Boolean(value))"
            />
          </template>
        </el-table-column>
        <el-table-column label="公网直连" min-width="125">
          <template #default="{ row }">
            <el-switch
              :model-value="!!row.frp_public_access"
              :disabled="!row.frp_public_access && (!row.frp_enabled || !overview?.config.is_active || !overview?.firewall.controller_ready)"
              :loading="deviceLoadingId === row.device_id"
              active-text="开启"
              inactive-text="隧道"
              @change="(value) => handleTogglePublicAccess(row, Boolean(value))"
            />
          </template>
        </el-table-column>
        <el-table-column label="SSH端口" min-width="120">
          <template #default="{ row }">
            <span class="monospace port-value" :class="{ editable: row.can_reassign_ports }"
              :title="portTitle(row)" @dblclick="openPortEditor(row, 'ssh_port')">
              {{ row.frp_ssh_port ?? '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Web端口" min-width="120">
          <template #default="{ row }">
            <span class="monospace port-value" :class="{ editable: row.can_reassign_ports }"
              :title="portTitle(row)" @dblclick="openPortEditor(row, 'web_port')">
              {{ row.frp_web_port ?? '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="隧道状态" min-width="120">
          <template #default="{ row }">
            <el-tag :type="getFrpTagType(row.frp_status)">
              {{ getFrpStatusText(row.frp_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="SSH命令" min-width="260">
          <template #default="{ row }">
            <div v-if="row.frp_public_access && row.ssh_connection_string" class="ssh-cell">
              <code class="ssh-code">{{ row.ssh_connection_string }}</code>
              <el-button type="primary" link @click="copyText(row.ssh_connection_string, 'SSH 命令')">复制</el-button>
            </div>
            <span v-else class="text-muted">通过 jetson_remote 隧道</span>
          </template>
        </el-table-column>
        <el-table-column label="Web访问" min-width="240">
          <template #default="{ row }">
            <div v-if="row.frp_public_access && row.web_access_url" class="ssh-cell">
              <code class="ssh-code">{{ row.web_access_url }}</code>
              <el-button type="primary" link @click="copyText(row.web_access_url, 'Web 地址')">复制</el-button>
            </div>
            <span v-else class="text-muted">通过 jetson_remote 隧道</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-tooltip :content="portResetTitle(row)" :disabled="!!row.can_reassign_ports">
              <span class="reset-action-wrap">
                <el-button type="warning" link :icon="Refresh" :disabled="!row.can_reassign_ports"
                  :loading="deviceLoadingId === row.device_id" @click="handleResetPorts(row)">重置端口</el-button>
              </span>
            </el-tooltip>
            <el-button type="primary" link @click="goToDevice(row.device_id)">设备详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  getFrpOverview, updateFrpConfig, syncFrpConfig, controlFrpService,
  setFrpPublicAccess, updateFrpPort, resetFrpPorts,
} from '@/api/frp'
import { setDeviceFrpEnabled } from '@/api/device'
import type { Device, FrpOverview, FrpServiceStatus, FrpStatus } from '@/types'
import { copyToClipboard } from '@/utils/clipboard'

const router = useRouter()

const loading = ref(false)
const savingConfig = ref(false)
const serviceActionLoading = ref(false)
const deviceLoadingId = ref('')
const searchText = ref('')
const overview = ref<FrpOverview | null>(null)
let firewallRefreshTimer: ReturnType<typeof setTimeout> | undefined
const configForm = ref({
  server_addr: '',
  server_port: 80,
  token: '',
  port_pool_start: 0,
  port_pool_end: 0,
  is_active: true,
  description: '',
})

const filteredDevices = computed(() => {
  const devices = overview.value?.devices || []
  if (!searchText.value) {
    return devices
  }

  const keyword = searchText.value.toLowerCase()
  return devices.filter((device) =>
    device.device_id.toLowerCase().includes(keyword) ||
    (device.name || '').toLowerCase().includes(keyword) ||
    (device.ip_address || '').toLowerCase().includes(keyword)
  )
})

const applyOverview = (data: FrpOverview) => {
  overview.value = data
  configForm.value = {
    server_addr: data.config.server_addr,
    server_port: data.config.server_port,
    token: data.config.token,
    port_pool_start: data.config.port_pool_start,
    port_pool_end: data.config.port_pool_end,
    is_active: data.config.is_active,
    description: data.config.description || '',
  }
}

const loadOverview = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const data = await getFrpOverview()
    applyOverview(data)
  } finally {
    loading.value = false
    if (overview.value?.firewall.state !== 'applied') {
      clearTimeout(firewallRefreshTimer)
      firewallRefreshTimer = setTimeout(() => void loadOverview(), overview.value?.firewall.state === 'pending' ? 3000 : 10000)
    } else {
      clearTimeout(firewallRefreshTimer)
    }
  }
}

const handleSaveConfig = async () => {
  savingConfig.value = true
  try {
    const data = await updateFrpConfig(configForm.value)
    applyOverview(data)
    ElMessage.success(data.message || 'FRP 配置已保存')
  } finally {
    savingConfig.value = false
  }
}

const handleSync = async () => {
  serviceActionLoading.value = true
  try {
    const data = await syncFrpConfig()
    applyOverview(data)
    ElMessage.success(data.message || 'FRP 配置已重新同步')
  } finally {
    serviceActionLoading.value = false
  }
}

const handleServiceAction = async (action: 'start' | 'stop' | 'restart') => {
  serviceActionLoading.value = true
  try {
    const data = await controlFrpService(action)
    applyOverview(data)
    ElMessage.success(data.message || `FRP 服务已${action}`)
  } finally {
    serviceActionLoading.value = false
  }
}

const handleToggleDeviceFrp = async (deviceId: string, enabled: boolean) => {
  deviceLoadingId.value = deviceId
  try {
    const result = await setDeviceFrpEnabled(deviceId, enabled)
    ElMessage.success(result.message)
    await loadOverview()
  } finally {
    deviceLoadingId.value = ''
  }
}

const handleTogglePublicAccess = async (row: Device, enabled: boolean) => {
  if (enabled) {
    try {
      await ElMessageBox.confirm(
        `将允许公网直接访问 ${row.name || row.device_id} 的 SSH ${row.frp_ssh_port} 和 Web ${row.frp_web_port} 端口。`,
        '开启公网直连',
        { type: 'warning', confirmButtonText: '开启直连', cancelButtonText: '取消' },
      )
    } catch {
      await loadOverview()
      return
    }
  }

  deviceLoadingId.value = row.device_id
  try {
    const result = await setFrpPublicAccess(row.device_id, enabled)
    if (result.firewall.policy_applied) {
      ElMessage.success(enabled ? '公网直连已开启' : '公网直连已关闭')
    } else if (result.firewall.state === 'error') {
      ElMessage.error(`策略已保存但未生效：${result.firewall.error || '宿主防火墙应用失败'}`)
    } else if (result.firewall.state === 'unavailable') {
      ElMessage.warning('关闭请求已保存，但宿主防火墙控制器离线，实际规则尚未确认')
    } else {
      ElMessage.info('策略已提交，正在等待宿主防火墙应用')
    }
    await loadOverview()
  } finally {
    deviceLoadingId.value = ''
  }
}

const portTitle = (row: Device) => row.can_reassign_ports
  ? '双击修改；SSH 与 Web 始终保持相邻端口'
  : '先停用 FRP，并等待设备确认隧道断开后，才能双击修改端口'

const portResetTitle = (row: Device) => row.frp_enabled
  ? '先停用设备 FRP'
  : '等待设备回报隧道已断开后可重置'

const openPortEditor = async (row: Device, field: 'ssh_port' | 'web_port') => {
  if (!row.can_reassign_ports) {
    ElMessage.warning(portTitle(row))
    return
  }
  const currentPort = field === 'ssh_port' ? row.frp_ssh_port : row.frp_web_port
  if (currentPort == null) return
  const label = field === 'ssh_port' ? 'SSH' : 'Web'
  try {
    const { value } = await ElMessageBox.prompt(
      `${label} 和另一端口會作為相邻端口对一起移动。`,
      `修改 ${label} 端口`,
      {
        inputValue: String(currentPort),
        inputType: 'number',
        inputPattern: /^[1-9]\d{0,4}$/,
        inputErrorMessage: '请输入 1 到 65535 的端口号',
        confirmButtonText: '保存端口',
        cancelButtonText: '取消',
      },
    )
    deviceLoadingId.value = row.device_id
    await updateFrpPort(row.device_id, field, Number(value))
    ElMessage.success('SSH/Web 端口对已更新')
    await loadOverview()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  } finally {
    deviceLoadingId.value = ''
  }
}

const handleResetPorts = async (row: Device) => {
  if (!row.can_reassign_ports) {
    ElMessage.warning(portResetTitle(row))
    return
  }
  try {
    await ElMessageBox.confirm(
      `将为 ${row.name || row.device_id} 重新分配一个空闲的 SSH/Web 相邻端口对。`,
      '重置设备端口',
      { type: 'warning', confirmButtonText: '重置端口', cancelButtonText: '取消' },
    )
    deviceLoadingId.value = row.device_id
    const result = await resetFrpPorts(row.device_id)
    ElMessage.success(`${result.message}${result.firewall.policy_applied ? '' : '，防火墙策略同步中'}`)
    await loadOverview()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  } finally {
    deviceLoadingId.value = ''
  }
}

const getFirewallAlertType = (state?: FrpOverview['firewall']['state']) =>
  state === 'error' ? 'error' : state === 'pending' ? 'info' : 'warning'

const getFirewallAlertText = (firewall?: FrpOverview['firewall']) => {
  if (firewall?.state === 'error') return `宿主防火墙规则应用失败：${firewall.error || '请检查宿主更新服务日志'}`
  if (firewall?.state === 'pending') return '端口访问策略正在同步；同步完成前请以此状态为准，不要假定公网规则已经改变。'
  return '宿主防火墙控制器未就绪；公网访问策略无法确认，设备仍可通过 SSH 隧道访问。'
}

const copyText = async (text: string, label = '内容') => {
  try {
    await copyToClipboard(text)
    ElMessage.success(`${label}已复制`)
  } catch (error) {
    ElMessage.error('复制失败，请手动复制')
  }
}

const goToDevice = (deviceId: string) => {
  router.push(`/devices/${deviceId}`)
}

const getServiceTagType = (status?: FrpServiceStatus) => {
  const map: Record<string, string> = {
    running: 'success',
    exited: 'warning',
    created: 'info',
    restarting: 'warning',
    paused: 'info',
    dead: 'danger',
    missing: 'danger',
    error: 'danger',
    unknown: 'info',
  }
  return map[status || 'unknown'] || 'info'
}

const getServiceStatusText = (status?: FrpServiceStatus) => {
  const map: Record<string, string> = {
    running: '运行中',
    exited: '已停止',
    created: '已创建',
    restarting: '重启中',
    paused: '已暂停',
    dead: '已终止',
    missing: '容器不存在',
    error: '状态异常',
    unknown: '未知',
  }
  return map[status || 'unknown'] || '未知'
}

const getFrpTagType = (status?: FrpStatus) => {
  const map: Record<string, string> = {
    connected: 'success',
    disconnected: 'info',
    connecting: 'warning',
    error: 'danger',
  }
  return map[status || 'disconnected'] || 'info'
}

const getFrpStatusText = (status?: FrpStatus) => {
  const map: Record<string, string> = {
    connected: '已连接',
    disconnected: '未连接',
    connecting: '连接中',
    error: '异常',
  }
  return map[status || 'disconnected'] || '未连接'
}

const getDeviceStatusTagType = (status?: Device['status']) => {
  const map: Record<string, string> = {
    online: 'success',
    offline: 'info',
    waiting: 'warning',
    deploying: 'warning',
    updating: 'warning',
    error: 'danger',
  }
  return map[status || 'offline'] || 'info'
}

const getDeviceStatusText = (status?: Device['status']) => {
  const map: Record<string, string> = {
    online: '在线',
    offline: '离线',
    waiting: '等待中',
    deploying: '部署中',
    updating: '更新中',
    error: '异常',
  }
  return map[status || 'offline'] || '离线'
}

const formatStartedAt = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

onMounted(() => {
  loadOverview()
})

onUnmounted(() => clearTimeout(firewallRefreshTimer))
</script>

<style scoped>
.frp-manage {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.page-subtitle {
  margin: 8px 0 0;
  color: #909399;
  font-size: 14px;
}

.summary-row,
.main-row {
  margin-bottom: 20px;
}

.summary-card {
  min-height: 140px;
}

.summary-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 16px;
}

.summary-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}

.summary-help {
  margin-top: 16px;
  color: #909399;
  font-size: 13px;
}

.monospace {
  font-family: monospace;
}

.port-value.editable {
  cursor: pointer;
  text-decoration: underline dotted var(--el-color-primary);
  text-underline-offset: 3px;
}

.reset-action-wrap {
  display: inline-flex;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.config-alert {
  margin-bottom: 20px;
}

.service-desc {
  margin-bottom: 20px;
}

.service-actions {
  width: 100%;
}

.devices-card {
  margin-bottom: 20px;
}

.firewall-alert {
  margin-bottom: 16px;
}

.access-hint {
  margin-bottom: 16px;
}

.device-search {
  width: 280px;
  max-width: 100%;
}

.device-name-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.device-name {
  font-weight: 600;
  color: #303133;
}

.device-sub,
.text-muted {
  color: #909399;
  font-size: 12px;
}

.form-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}

.ssh-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ssh-code {
  display: inline-block;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #f5f7fa;
  padding: 4px 8px;
  border-radius: 4px;
}

@media (max-width: 768px) {
  .page-header,
  .card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .device-search {
    width: 100%;
  }

  .ssh-cell {
    flex-direction: column;
    align-items: flex-start;
  }

  .ssh-code {
    max-width: 100%;
  }
}
</style>
