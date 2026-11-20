<template>
  <section class="log-panel">
    <el-form inline class="log-filters" @submit.prevent="applyFilters">
      <el-form-item label="时间"><el-date-picker v-model="range" type="datetimerange" popper-class="system-log-dates" start-placeholder="开始时间" end-placeholder="结束时间" @change="rollingRange = false" /></el-form-item>
      <el-form-item label="级别"><el-select v-model="filters.level" clearable placeholder="全部"><el-option v-for="level in logLevels" :key="level" :value="level" /></el-select></el-form-item>
      <el-form-item label="模块"><el-select v-model="filters.module" clearable filterable allow-create placeholder="全部"><el-option v-for="(label, value) in logModuleLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
      <el-form-item label="操作人"><el-input v-model="filters.actor" clearable placeholder="操作人" /></el-form-item>
      <el-form-item label="结果"><el-select v-model="filters.result" clearable placeholder="全部"><el-option v-for="(label, value) in resultLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
      <el-form-item label="搜索"><el-input v-model="filters.search" clearable placeholder="关键词" /></el-form-item>
      <el-form-item><el-button type="primary" native-type="submit" :disabled="busy">查询</el-button><el-button @click="reset">重置</el-button></el-form-item>
    </el-form>
    <div class="log-toolbar">
      <el-button :loading="busy" :disabled="busy || !connected" @click="load">刷新</el-button>
      <el-switch v-model="autoRefresh" active-text="每10秒自动刷新" />
      <span v-if="autoRefresh && (!visible || !connected || busy || drawer || filtersDirty)" class="log-status">自动刷新已暂停</span>
      <span class="log-status">最近获取：{{ formatLogTime(lastFetch) }}</span>
    </div>
    <el-alert v-if="error" class="log-alert" :title="error" type="error" :closable="false" show-icon />
    <div class="log-table-pane">
    <el-table v-loading="busy && !drawer" :data="rows" height="100%" border empty-text="暂无平台日志">
      <el-table-column label="时间" width="185"><template #default="{ row }">{{ formatLogTime(row.timestamp) }}</template></el-table-column>
      <el-table-column prop="level" label="级别" width="100" />
      <el-table-column label="模块" min-width="110"><template #default="{ row }">{{ logModuleLabels[row.module] || row.module }}</template></el-table-column>
      <el-table-column label="操作" min-width="130"><template #default="{ row }">{{ logActionLabels[row.action] || row.action }}</template></el-table-column>
      <el-table-column prop="actor" label="操作人" width="110" />
      <el-table-column prop="target" label="目标" min-width="140" show-overflow-tooltip />
      <el-table-column label="结果" width="95"><template #default="{ row }"><el-tag :type="row.result === 'failed' ? 'danger' : row.result === 'success' ? 'success' : 'info'">{{ resultLabels[row.result as PlatformLog['result']] || row.result }}</el-tag></template></el-table-column>
      <el-table-column prop="message" label="消息" min-width="240" show-overflow-tooltip />
      <el-table-column label="详情" width="80" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="busy" @click="showDetail(row)">查看</el-button></template></el-table-column>
    </el-table>
    </div>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" />
    <el-drawer v-model="drawer" title="平台日志详情" size="min(640px, 100%)" @close="cancel">
      <div v-loading="busy">
        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <template v-if="detail">
          <el-descriptions :column="1" border>
            <el-descriptions-item v-for="(value, label) in detailFields" :key="label" :label="label">{{ value || '-' }}</el-descriptions-item>
          </el-descriptions>
          <div class="log-toolbar"><el-button @click="copyDetail">复制</el-button><el-button @click="downloadLogText(detailText, `platform-${detail.id}.txt`)">下载 TXT</el-button></div>
          <pre class="log-text">{{ detail.detail || '无附加详情' }}</pre>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemLog, getSystemLogs, logModuleLabels, logActionLabels, type PlatformLog } from '@/api/systemLogs'
import { copyToClipboard } from '@/utils/clipboard'
import { downloadLogText, formatLogTime, last24Hours, logLevels, timeFilters, useLogRequest } from './useLogRequest'

const range = ref<[Date, Date] | null>(last24Hours())
const rollingRange = ref(true)
const filters = reactive({ level: '', module: '', actor: '', result: '', search: '' })
const appliedFilters = ref({ ...filters })
const appliedRange = ref<[Date, Date] | null>(range.value)
const appliedRolling = ref(true)
const filtersDirty = computed(() => JSON.stringify([filters, range.value, rollingRange.value]) !== JSON.stringify([appliedFilters.value, appliedRange.value, appliedRolling.value]))
const rows = ref<PlatformLog[]>([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const drawer = ref(false)
const detail = ref<PlatformLog>()
const resultLabels = { submitted: '已提交', success: '成功', failed: '失败' }
const { busy, error, lastFetch, autoRefresh, visible, connected, run, cancel } = useLogRequest(() => void load(), () => !drawer.value && !filtersDirty.value)

function load() {
  return run(signal => getSystemLogs({ ...timeFilters(appliedRolling.value ? last24Hours() : appliedRange.value), ...appliedFilters.value, page: page.value, page_size: pageSize.value }, signal), result => {
    rows.value = result.results
    total.value = result.count
  })
}
function applyFilters() {
  appliedFilters.value = { ...filters }; appliedRange.value = range.value; appliedRolling.value = rollingRange.value
  cancel(); rows.value = []; total.value = 0
  if (page.value !== 1) page.value = 1
  else void load()
}
function reset() { rollingRange.value = true; range.value = last24Hours(); Object.assign(filters, { level: '', module: '', actor: '', result: '', search: '' }); applyFilters() }
watch([page, pageSize], (_value, oldValue) => {
  cancel(); rows.value = []
  if (pageSize.value !== oldValue[1] && page.value !== 1) page.value = 1
  else void load()
})
function showDetail(row: PlatformLog) {
  detail.value = undefined
  drawer.value = true
  void run(signal => getSystemLog(String(row.id), signal), result => { detail.value = result })
}
const detailFields = computed(() => detail.value ? {
  ID: detail.value.id, 时间: formatLogTime(detail.value.timestamp), 级别: detail.value.level,
  模块: logModuleLabels[detail.value.module] || detail.value.module,
  操作: logActionLabels[detail.value.action] || detail.value.action, 操作人: detail.value.actor,
  目标: detail.value.target, 结果: resultLabels[detail.value.result], 消息: detail.value.message,
  设备: detail.value.device_id, 任务: detail.value.task_id,
} : {})
const detailText = computed(() => Object.entries(detailFields.value).map(([key, value]) => `${key}: ${value || '-'}`).join('\n') + `\n\n${detail.value?.detail || ''}`)
async function copyDetail() {
  try { await copyToClipboard(detailText.value); ElMessage.success('已复制') }
  catch { ElMessage.error('复制失败，请重试') }
}
onMounted(() => void load())
</script>
