<template>
  <div class="platform-settings">
    <h2>平台设置</h2>
    <el-card shadow="never">
      <template #header>
        <div class="card-heading">
          <strong>平台版本与更新</strong>
          <el-button :icon="Refresh" :loading="release.loading" :disabled="running"
            @click="release.load(true)">检查更新</el-button>
        </div>
      </template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="当前版本">{{ info?.current_version || '—' }}</el-descriptions-item>
        <el-descriptions-item label="最新版本">{{ info?.latest?.version || '—' }}</el-descriptions-item>
        <el-descriptions-item label="最近检查">{{ formatTime(info?.checked_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="running" class="notice" type="info" :closable="false"
        :title="release.unavailable ? '平台正在切换，正在等待服务恢复…' : labels[info!.job!.status]" />
      <el-alert v-else-if="release.unavailable || info?.check_failed" class="notice" type="warning"
        :closable="false" title="暂时无法检查更新，请稍后重试。" />
      <el-alert v-else-if="info && !info.updater_ready && canUpdate" class="notice" type="warning"
        :closable="false" title="宿主机更新服务尚未就绪。" />
      <el-alert v-else-if="info?.update_available" class="notice" type="info"
        :closable="false" :title="`发现新版本 ${info.latest?.version}`" />
      <el-alert v-else-if="info?.latest?.version === info?.current_version && info?.latest" class="notice" type="success" :closable="false"
        title="当前已是最新版本" />

      <div v-if="info?.latest" class="release-details">
        <div class="card-heading">
          <strong>发布说明</strong>
          <a :href="info.latest.url" target="_blank" rel="noopener noreferrer">查看 GitHub Release</a>
        </div>
        <pre v-if="info.latest.notes">{{ info.latest.notes }}</pre>
      </div>

      <div v-if="info?.job" class="notice" role="status">
        <strong>最近更新 {{ info.job.version }}</strong>
        <p>{{ labels[info.job.status] }}{{ info.job.message ? ` · ${info.job.message}` : '' }}</p>
      </div>
      <el-button v-if="canUpdate && info?.update_available" class="notice" type="primary"
        :disabled="running || !info.updater_ready || info.check_failed || release.unavailable ||
          info.job?.status === 'recovery_required'" :loading="submitting" @click="confirmUpdate">
        更新到 {{ info.latest?.version }}
      </el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getStoredUser } from '@/api/auth'
import { isUpdateRunning, usePlatformRelease, type UpdateJob } from '@/stores/platformRelease'

const release = usePlatformRelease()
const info = computed(() => release.info)
const running = computed(() => isUpdateRunning(info.value?.job))
const canUpdate = computed(() => !!getStoredUser()?.is_staff)
const submitting = ref(false)
const labels: Record<UpdateJob['status'], string> = {
  queued: '等待更新',
  preparing: '拉取镜像并预检',
  switching: '正在切换平台服务',
  rolling_back: '正在恢复上一版本',
  succeeded: '更新成功',
  failed: '更新失败',
  rolled_back: '更新失败，已恢复上一版本',
  recovery_required: '自动恢复未通过，请检查宿主机',
}

const formatTime = (timestamp?: number | null) =>
  timestamp ? new Date(timestamp * 1000).toLocaleString() : '—'

async function confirmUpdate() {
  const version = info.value?.latest?.version
  if (!version) return
  try {
    await ElMessageBox.confirm(
      `更新到 ${version}？切换时管理平台会短暂不可用。`,
      '确认平台更新',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    await release.apply(version)
  } catch {
    // The API client displays the reason; refresh in case the request was accepted.
    await release.load()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.platform-settings { max-width: 880px; }
.platform-settings h2 { margin: 0 0 20px; }
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.notice, .release-details { margin-top: 16px; }
.release-details a { color: var(--el-color-primary); }
.release-details pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  max-height: 280px;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}
</style>
