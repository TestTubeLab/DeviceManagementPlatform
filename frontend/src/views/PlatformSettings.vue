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

      <div v-if="running && info?.job" class="update-progress notice" role="status" aria-live="polite">
        <div class="card-heading">
          <strong>{{ release.unavailable ? '正在重新连接更新状态' : progress.title }}</strong>
          <el-tag size="small" type="warning">{{ progress.title }}</el-tag>
        </div>
        <el-steps :active="progress.activeStep" finish-status="success" simple>
          <el-step title="下载并校验镜像" />
          <el-step title="预检数据库迁移" />
          <el-step title="切换并验证" />
        </el-steps>
        <div v-if="progress.downloading" class="download-progress" role="group" aria-label="镜像下载进度">
          <el-progress :percentage="progress.downloadPercent" :stroke-width="9" :format="formatPercent" />
          <div class="download-metrics">
            <span><strong>已下载</strong> {{ formatBytes(info.job.downloaded_bytes) }} / {{ formatBytes(info.job.total_bytes) }}</span>
            <span><strong>速度</strong> {{ formatSpeed(info.job.download_speed_bytes_per_second) }}</span>
            <span><strong>最近进度</strong> {{ info.job.download_idle_seconds ?? 0 }} 秒前</span>
          </div>
          <el-alert v-if="(info.job.download_idle_seconds ?? 0) >= 15" type="warning" :closable="false"
            :title="`下载文件已 ${info.job.download_idle_seconds} 秒未增长。平台仍在运行；下载器可能正在等待网络或重试，请勿重复提交更新。`" />
        </div>
        <div v-else class="update-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100"
          :aria-valuetext="`${progress.title}，${release.unavailable ? '状态暂不可用，正在重试' : progress.detail}`">
          <span />
        </div>
        <p>{{ release.unavailable ? '暂时无法读取任务状态，页面正在自动重试；更新阶段可能造成短暂不可访问。' : progress.detail }}</p>
        <small>任务 {{ info.job.id }} · 阶段开始于 {{ formatTime(info.job.phase_started_at || info.job.updated_at || info.job.created_at) }}</small>
      </div>
      <el-alert v-else-if="info?.job?.status === 'rolled_back'" class="notice" type="warning" :closable="false"
        :title="`${labels[info.job.status]}${info.job.message ? ` · ${info.job.message}` : ''}`" />
      <el-alert v-else-if="info?.job?.status === 'failed' || info?.job?.status === 'recovery_required'" class="notice"
        type="error" :closable="false"
        :title="`${labels[info.job.status]}${info.job.message ? ` · ${info.job.message}` : ''}`" />
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

      <div v-if="info?.job && !running" class="notice" role="status">
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
const progress = computed(() => getUpdateProgress(info.value?.job))

function getUpdateProgress(job?: UpdateJob | null) {
  if (job?.status === 'switching') {
    return {
      activeStep: 2,
      title: job.message || '正在切换平台服务',
      detail: job.message || '镜像与数据库预检已通过，正在备份数据库、切换应用容器并等待健康检查。此阶段服务可能短暂中断。',
      downloading: false,
      downloadPercent: 0,
    }
  }
  if (job?.status === 'rolling_back') {
    return {
      activeStep: 2,
      title: job.message || '正在恢复上一版本',
      detail: job.message || '新版本未通过健康检查，正在恢复原应用容器和数据库。请保持页面打开，等待恢复结果。',
      downloading: false,
      downloadPercent: 0,
    }
  }
  const phaseTitles: Record<string, string> = {
    release_metadata: '正在检查发布版本',
    inspect_current: '正在检查当前平台容器',
    check_layout: '正在检查容器和数据卷',
    download: '正在下载发布镜像',
    verify_archive: '正在校验下载文件',
    load_image: '正在载入 Docker 镜像',
    verify_image: '正在校验镜像版本',
    cached_image: '正在复用已校验镜像',
    registry_pull: '正在从镜像仓库拉取',
    preflight_snapshot: '正在准备数据库预检',
    preflight_migrations: '正在预检数据库迁移',
    stage_updater: '正在校验宿主更新器',
  }
  const phase = job?.phase || ''
  const downloading = phase === 'download' && (job?.total_bytes || 0) > 0
  const downloadedBytes = Math.max(0, job?.downloaded_bytes || 0)
  const totalBytes = Math.max(0, job?.total_bytes || 0)
  return {
    activeStep: phase.startsWith('preflight') || phase === 'stage_updater' ? 1 : 0,
    title: job?.status === 'queued'
      ? '更新任务已排队'
      : phaseTitles[phase] || '正在准备更新',
    detail: job?.message || (job?.status === 'queued'
      ? '宿主机更新器即将开始处理。'
      : '正在准备发布镜像，随后会预检数据库迁移。此阶段旧版平台继续运行。'),
    downloading,
    downloadPercent: totalBytes > 0
      ? Math.min(100, Math.max(0, job?.download_percent ?? downloadedBytes * 100 / totalBytes))
      : 0,
  }
}

function formatBytes(value?: number) {
  const bytes = Math.max(0, value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatSpeed(value?: number) {
  return `${formatBytes(value)}/s`
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`
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
.update-progress { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 4px; }
.download-progress { display: grid; gap: 10px; }
.download-metrics { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; color: var(--el-text-color-regular); }
.download-metrics strong { color: var(--el-text-color-primary); }
.update-progress-track { height: 8px; overflow: hidden; background: var(--el-fill-color); border-radius: 4px; }
.update-progress-track span {
  display: block;
  width: 32%;
  height: 100%;
  background: var(--el-color-primary);
  border-radius: inherit;
  animation: update-progress-slide 1.8s ease-in-out infinite alternate;
}
@keyframes update-progress-slide {
  from { transform: translateX(0); }
  to { transform: translateX(212%); }
}
@media (prefers-reduced-motion: reduce) {
  .update-progress-track span { animation: none; transform: translateX(106%); }
}
.update-progress p { margin: 0; color: var(--el-text-color-regular); }
.update-progress small { color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
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
