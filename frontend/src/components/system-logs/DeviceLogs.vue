<template>
  <section class="log-panel">
    <div class="log-toolbar">
      <el-select v-model="deviceId" filterable placeholder="选择设备" style="width: min(360px, 100%)" :disabled="busy && !devices.length">
        <el-option v-for="item in devices" :key="item.device_id" :value="item.device_id" :label="`${item.name || item.device_id} (${item.device_id})`" />
      </el-select>
      <el-select v-model="source" placeholder="日志来源" style="width: 190px">
        <el-option label="容器日志（已保存）" value="container" />
        <el-option label="业务文件日志" value="business" />
        <el-option label="Agent 服务" value="agent" />
        <el-option label="FRPC 服务" value="frpc" />
        <el-option label="Docker 服务" value="docker" />
        <el-option label="系统 journal" value="system" />
      </el-select>
      <el-tag v-if="device" :type="online ? 'success' : 'info'">{{ online ? '在线' : '离线' }}</el-tag>
      <span v-if="device" class="log-status">Agent {{ device.agent_version || '未知' }}</span>
      <el-button link type="primary" :disabled="busy || !deviceId || !connected" @click="refreshDevice">刷新设备状态</el-button>
    </div>
    <el-alert v-if="device && !online" title="设备离线，可查看已保存的容器日志；远程日志操作已停用。" type="info" :closable="false" class="log-alert" />
    <el-alert v-if="isJournal && device && !supportsServiceLogs(device.agent_version)" type="warning" :closable="false" class="log-alert">
      <template #title>服务日志需要 Agent 1.7.3 或更高版本，当前为 {{ device.agent_version || '未知' }}</template>
      <el-button size="small" :disabled="!online || busy || !connected" @click="upgradeAgent">升级 Agent</el-button>
      <span v-if="upgradeSubmitted" class="log-status"> 升级请求已提交，请稍后刷新设备状态</span>
    </el-alert>
    <el-form inline class="log-filters" @submit.prevent="query">
      <el-form-item label="时间"><el-date-picker v-model="range" type="datetimerange" popper-class="system-log-dates" start-placeholder="开始时间" end-placeholder="结束时间" @change="rollingRange = false" /></el-form-item>
      <el-form-item label="级别"><el-select v-model="level" clearable placeholder="全部"><el-option v-for="item in logLevels" :key="item" :value="item" /></el-select></el-form-item>
      <el-form-item label="搜索"><el-input v-model="keyword" clearable placeholder="关键词" /></el-form-item>
      <el-form-item v-if="source !== 'container'" label="行数"><el-input-number v-model="lines" :min="1" :max="2000" /></el-form-item>
      <el-form-item><el-button type="primary" native-type="submit" :disabled="busy || !canRead">{{ source === 'business' ? '搜索文件' : '查询' }}</el-button><el-button @click="resetFilters">重置</el-button></el-form-item>
    </el-form>
    <div v-if="source === 'business'" class="log-toolbar">
      <el-button :disabled="busy || !canRead" @click="loadRemote('list')">获取文件列表</el-button>
      <el-select v-model="fileKey" filterable placeholder="选择日期 / 文件" style="width: min(420px, 100%)" :disabled="busy || !canRead" @change="loadRemote('read')">
        <el-option-group v-for="date in files.dates" :key="date" :label="date">
          <el-option v-for="file in files.files[date] || []" :key="`${date}/${file}`" :label="`${date} / ${file}`" :value="`${date}/${file}`" />
        </el-option-group>
      </el-select>
      <el-switch v-model="tail" active-text="读取末尾" />
      <el-button :disabled="busy || !canRead || !fileKey" @click="loadRemote('read')">读取文件</el-button>
      <el-button :disabled="busy || !canRead || !fileKey" @click="loadRemote('download')">下载原始 ZIP</el-button>
    </div>
    <div class="log-toolbar">
      <el-button :loading="busy" :disabled="busy || !canRead" @click="refresh">{{ isJournal ? '采集日志' : '刷新' }}</el-button>
      <el-button v-if="busy" @click="cancel">取消</el-button>
      <el-switch v-model="autoRefresh" active-text="每10秒自动刷新" />
      <span v-if="autoRefresh && (!visible || !connected || busy || !online || !canRead || filtersDirty)" class="log-status">自动刷新已暂停</span>
      <span class="log-status">最近获取：{{ formatLogTime(lastFetch) }}</span>
    </div>
    <el-alert v-if="!connected" title="网络离线，已暂停请求" type="warning" :closable="false" class="log-alert" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="log-alert" show-icon />
    <el-empty v-if="!devices.length && !busy" description="暂无设备"><el-button @click="loadDevices">重新获取设备</el-button></el-empty>
    <template v-else-if="deviceId">
      <template v-if="source === 'container'">
        <div class="log-table-pane">
        <el-table v-loading="busy" :data="rows" height="100%" border empty-text="暂无已保存的容器日志">
          <el-table-column label="时间" width="185"><template #default="{ row }">{{ formatLogTime(row.timestamp) }}</template></el-table-column>
          <el-table-column prop="device_name" label="设备" min-width="120" />
          <el-table-column prop="level" label="级别" width="100" />
          <el-table-column prop="message" label="消息" min-width="320"><template #default="{ row }"><span class="saved-message">{{ row.message }}</span></template></el-table-column>
        </el-table>
        </div>
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" />
      </template>
      <template v-else>
        <div v-loading="busy" class="log-content-pane"><pre v-if="content" class="log-text" tabindex="0" aria-label="日志内容">{{ content }}</pre><el-empty v-else :description="busy ? '正在获取日志…' : '暂无日志，请选择来源后采集或读取'" /></div>
        <p class="log-status content-meta">{{ contentMeta }}</p>
      </template>
      <div class="log-toolbar">
        <el-button :disabled="!currentText || busy" @click="copyCurrent">复制当前内容</el-button>
        <el-button :disabled="!currentText || busy" @click="downloadLogText(currentText, `${deviceId}-${source}.txt`)">下载当前 TXT</el-button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Device } from '@/types'
import { updateAgent } from '@/api/device'
import {
  collectServiceLogs, createLogTask, getLogDevice, getLogDevices, getLogsPage, supportsServiceLogs, waitForLogTask,
  type BusinessArchive, type BusinessContent, type BusinessFiles, type BusinessSearch, type JournalResult,
  type JournalSource, type SavedDeviceLog,
} from '@/api/systemLogs'
import { isDeviceCurrentlyOnline } from '@/utils/deviceStatus'
import { copyToClipboard } from '@/utils/clipboard'
import { downloadLogBlob, downloadLogText, formatLogTime, last24Hours, logLevels, timeFilters, useLogRequest } from './useLogRequest'

const devices = ref<Device[]>([])
const deviceId = ref('')
const source = ref<'container' | 'business' | JournalSource>('container')
const device = computed(() => devices.value.find(item => item.device_id === deviceId.value))
const online = computed(() => !!device.value && isDeviceCurrentlyOnline(device.value))
const isJournal = computed(() => source.value !== 'container' && source.value !== 'business')
const range = ref<[Date, Date] | null>(last24Hours())
const rollingRange = ref(true)
const level = ref('')
const keyword = ref('')
const lines = ref(500)
const tail = ref(true)
const filterSnapshot = () => ({ range: range.value, rolling: rollingRange.value, level: level.value, keyword: keyword.value, lines: lines.value, tail: tail.value })
const applied = ref(filterSnapshot())
const filtersDirty = computed(() => JSON.stringify(filterSnapshot()) !== JSON.stringify(applied.value))
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const rows = ref<SavedDeviceLog[]>([])
const files = ref<BusinessFiles>({ dates: [], files: {} })
const fileKey = ref('')
const content = ref('')
const contentMeta = ref('')
const searchMode = ref(false)
const upgradeSubmitted = ref(false)
const { busy, error, lastFetch, autoRefresh, visible, connected, run, cancel } = useLogRequest(
  () => void refresh(), () => online.value && canRead.value && !filtersDirty.value,
)
const canRead = computed(() => !!device.value && connected.value && (source.value === 'container' || (
  online.value && (!isJournal.value || supportsServiceLogs(device.value.agent_version))
)))
const currentText = computed(() => source.value === 'container'
  ? rows.value.map(row => `${row.timestamp} [${row.level}] ${row.message}`).join('\n')
  : content.value)

function loadDevices() {
  return run(getLogDevices, result => {
    devices.value = result
    if (!deviceId.value) deviceId.value = result[0]?.device_id || ''
  })
}

async function checkDevice(signal: AbortSignal, id: string, remote: boolean) {
  const fresh = await getLogDevice(id, signal)
  signal.throwIfAborted()
  devices.value = devices.value.map(item => item.device_id === id ? fresh : item)
  if (remote && !isDeviceCurrentlyOnline(fresh)) throw new Error('设备已离线，远程日志操作已停用')
  if (remote && isJournal.value && !supportsServiceLogs(fresh.agent_version)) throw new Error('请先升级 Agent 至 1.7.3 或更高版本')
  return fresh
}

function loadSaved() {
  if (!deviceId.value || !connected.value) return
  const id = deviceId.value
  const params = { ...timeFilters(applied.value.rolling ? last24Hours() : applied.value.range), device_id: id, level: applied.value.level, search: applied.value.keyword, page: page.value, page_size: pageSize.value }
  return run(async signal => {
    await checkDevice(signal, id, false)
    return getLogsPage(params, signal)
  }, result => { rows.value = result.results; total.value = result.count })
}

/** Snapshot the device/source/options before creating a task; all steps share one signal. */
function loadRemote(operation: 'list' | 'read' | 'search' | 'download' | 'journal') {
  if (!canRead.value || busy.value || source.value === 'container') return
  const id = deviceId.value
  const selectedSource = source.value
  const dateRange = rollingRange.value ? last24Hours() : range.value
  const selectedRange = timeFilters(dateRange)
  const [date, ...fileParts] = fileKey.value.split('/')
  const file = fileParts.join('/')
  const selectedLines = Math.min(2000, Math.max(1, lines.value || 500))
  if ((operation === 'read' || operation === 'download') && (!date || !file)) { error.value = '请先选择日志文件'; return }
  if (operation === 'search' && !keyword.value.trim()) { error.value = '请输入搜索关键词'; return }
  applied.value = filterSnapshot()
  if (operation === 'read' || operation === 'search' || operation === 'journal') {
    content.value = ''; contentMeta.value = ''
  }
  return run(async signal => {
    await checkDevice(signal, id, true)
    if (operation === 'journal') {
      const task = await collectServiceLogs(id, {
        source: selectedSource as JournalSource, ...selectedRange, lines: selectedLines,
        level: level.value || undefined, keyword: keyword.value.trim() || undefined,
      }, signal)
      const result = await waitForLogTask<JournalResult>(id, task.task_id, signal)
      return { content: result.content, meta: `${result.source} / ${result.returned_lines} 行${result.truncated ? ' / 已截断' : ''} / 采集于 ${formatLogTime(result.collected_at)}` }
    }
    if (operation === 'list') {
      const task = await createLogTask(id, 'list_logs', {}, signal)
      return { files: await waitForLogTask<BusinessFiles>(id, task.task_id, signal) }
    }
    if (operation === 'read') {
      const task = await createLogTask(id, 'read_log', { date, file, lines: selectedLines, tail: tail.value }, signal)
      const result = await waitForLogTask<BusinessContent>(id, task.task_id, signal)
      return { content: result.content, meta: `${date} / ${file} / ${result.returned_lines} 行，共 ${result.total_lines} 行${result.truncated ? ' / 已截断' : ''}`, search: false }
    }
    if (operation === 'search') {
      const task = await createLogTask(id, 'search_logs', {
        keyword: keyword.value.trim(), level: level.value || undefined, case_sensitive: false,
        start_date: dateRange ? localDate(dateRange[0]) : undefined,
        end_date: dateRange ? localDate(dateRange[1]) : undefined,
      }, signal)
      const result = await waitForLogTask<BusinessSearch>(id, task.task_id, signal)
      return {
        content: result.matches.map(match => `${match.date}/${match.file}:${match.line_num}\n${match.content}`).join('\n\n'),
        meta: `匹配 ${result.total_matches} 条${result.truncated ? ' / 已截断' : ''}`, search: true,
      }
    }
    const task = await createLogTask(id, 'download_log', { date, files: [file] }, signal)
    return { archive: await waitForLogTask<BusinessArchive>(id, task.task_id, signal) }
  }, result => {
    if ('files' in result && result.files) {
      files.value = result.files
      if (!files.value.dates.some(day => (files.value.files[day] || []).some(name => `${day}/${name}` === fileKey.value))) fileKey.value = ''
      contentMeta.value = `已获取 ${files.value.dates.length} 天的文件列表`
    }
    if ('content' in result) { content.value = result.content || ''; contentMeta.value = result.meta || '' }
    if ('search' in result) searchMode.value = !!result.search
    if ('archive' in result && result.archive) {
      const bytes = Uint8Array.from(atob(result.archive.content), char => char.charCodeAt(0))
      downloadLogBlob(new Blob([bytes], { type: 'application/zip' }), result.archive.filename)
    }
  })
}

function localDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
function refresh() {
  if (source.value === 'container') return loadSaved()
  if (!canRead.value) return
  return loadRemote(isJournal.value ? 'journal' : searchMode.value ? 'search' : fileKey.value ? 'read' : 'list')
}
function refreshDevice() {
  if (!deviceId.value || !connected.value) return
  const id = deviceId.value
  return run(signal => getLogDevice(id, signal), fresh => {
    devices.value = devices.value.map(item => item.device_id === fresh.device_id ? fresh : item)
  })
}
function query() {
  applied.value = filterSnapshot()
  if (source.value === 'container') {
    cancel(); rows.value = []; total.value = 0
    if (page.value !== 1) page.value = 1
    else void loadSaved()
  }
  else void loadRemote(isJournal.value ? 'journal' : 'search')
}
function resetFilters() {
  rollingRange.value = true; range.value = last24Hours(); level.value = ''; keyword.value = ''; lines.value = 500
  if (source.value === 'container') query()
}
function clearDisplay() {
  rows.value = []; total.value = 0; content.value = ''; contentMeta.value = ''; lastFetch.value = ''; error.value = ''
}
watch([deviceId, source], () => {
  cancel(); clearDisplay(); files.value = { dates: [], files: {} }; fileKey.value = ''; searchMode.value = false; upgradeSubmitted.value = false
  applied.value = filterSnapshot()
  if (page.value !== 1) page.value = 1
  else if (source.value === 'container') void loadSaved()
})
watch([page, pageSize], (_value, oldValue) => {
  cancel()
  if (pageSize.value !== oldValue[1] && page.value !== 1) page.value = 1
  else if (source.value === 'container') void loadSaved()
})
watch(online, value => { if (!value && source.value !== 'container') cancel() })

async function upgradeAgent() {
  if (!device.value || !online.value || busy.value) return
  // Reuse the existing explicit upgrade action; never upgrade while collecting logs.
  const id = deviceId.value
  await run(() => updateAgent(id), () => { upgradeSubmitted.value = true; ElMessage.success('Agent 升级请求已提交') })
}
async function copyCurrent() {
  try { await copyToClipboard(currentText.value); ElMessage.success('已复制') }
  catch { ElMessage.error('复制失败，请重试') }
}
onMounted(() => void loadDevices())
</script>

<style scoped>
.saved-message { white-space: pre-wrap; overflow-wrap: anywhere; }
.content-meta { margin-top: 8px; }
</style>
