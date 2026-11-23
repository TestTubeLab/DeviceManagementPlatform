import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '@/api/request'

export interface UpdateJob {
  id: string
  version: string
  status: 'queued' | 'preparing' | 'switching' | 'rolling_back' | 'succeeded' | 'failed' | 'rolled_back' | 'recovery_required'
  created_at: number
  updated_at?: number
  actor: string
  message?: string
}

interface ReleaseStatus {
  current_version: string
  latest: { version: string; notes: string; url: string; published_at: string } | null
  update_available: boolean
  check_failed: boolean
  updater_ready: boolean
  checked_at: number | null
  job: UpdateJob | null
}

export const isUpdateRunning = (job?: UpdateJob | null) =>
  !!job && ['queued', 'preparing', 'switching', 'rolling_back'].includes(job.status)

export const usePlatformRelease = defineStore('platformRelease', () => {
  const info = ref<ReleaseStatus | null>(null)
  const loading = ref(false)
  const unavailable = ref(false)

  async function load(refresh = false) {
    if (loading.value) return
    loading.value = true
    try {
      // A brief 503 while the container is replaced is expected during polling.
      const response = await fetch(`/api/platform/release/${refresh ? '?refresh=true' : ''}`, {
        headers: { Authorization: `Token ${localStorage.getItem('token') || ''}` },
        cache: 'no-store',
        signal: AbortSignal.timeout(15000),
      })
      if (!response.ok) throw new Error('Platform release status unavailable')
      const next: ReleaseStatus = await response.json()
      const previous = info.value
      info.value = next
      unavailable.value = false
      if (previous && previous.current_version !== next.current_version &&
          next.job?.status === 'succeeded' && next.job.version === next.current_version) {
        window.location.reload()
      }
    } catch {
      unavailable.value = true
    } finally {
      loading.value = false
    }
  }

  async function apply(version: string) {
    const job: UpdateJob = await request.post('/platform/updates/', { version }, { timeout: 25000 })
    if (info.value) info.value.job = job
  }

  return { info, loading, unavailable, load, apply }
})
