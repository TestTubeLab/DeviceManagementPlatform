import { onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'

export const logLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
export const last24Hours = (): [Date, Date] => [new Date(Date.now() - 86400000), new Date()]
export const timeFilters = (range: [Date, Date] | null) => range ? {
  start_time: range[0].toISOString(), end_time: range[1].toISOString(),
} : {}
export const formatLogTime = (value: string) => value ? new Date(value).toLocaleString() : '-'

/** One active operation per mounted tab, including task creation and polling. */
export function useLogRequest(refresh: () => void, canAutoRefresh = () => true) {
  const busy = ref(false)
  const error = ref('')
  const lastFetch = ref('')
  const autoRefresh = ref(false)
  const visible = ref(!document.hidden)
  const connected = ref(navigator.onLine)
  let current: AbortController | undefined
  let refreshTimer: number | undefined

  function cancel() {
    current?.abort()
    current = undefined
    busy.value = false
  }

  async function run<T>(load: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void) {
    if (busy.value) return
    const controller = new AbortController()
    current = controller
    busy.value = true
    error.value = ''
    let timedOut = false
    const deadline = window.setTimeout(() => { timedOut = true; controller.abort() }, 60000)
    let onAbort: () => void = () => {}
    const aborted = new Promise<never>((_resolve, reject) => {
      onAbort = () => reject(new DOMException('Aborted', 'AbortError'))
      controller.signal.addEventListener('abort', onAbort, { once: true })
    })
    try {
      const value = await Promise.race([load(controller.signal), aborted])
      // Device/source/filter changes may finish an old request after cancellation.
      if (current !== controller || controller.signal.aborted) return
      apply(value)
      lastFetch.value = new Date().toISOString()
    } catch (cause) {
      if (current !== controller) return
      if (timedOut) error.value = '请求超时（60秒），请重试'
      else if (!controller.signal.aborted && !axios.isCancel(cause)) {
        const data = axios.isAxiosError(cause) ? cause.response?.data : undefined
        const message = data?.error || data?.detail
        error.value = typeof message === 'string' ? message : data && typeof data === 'object'
          ? Object.entries(data).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('；') : String(value)}`).join('；')
          : cause instanceof Error ? cause.message : '请求失败，请重试'
      }
    } finally {
      window.clearTimeout(deadline)
      controller.signal.removeEventListener('abort', onAbort)
      if (current === controller) { current = undefined; busy.value = false }
    }
  }

  const visibilityChanged = () => { visible.value = !document.hidden }
  const connectivityChanged = () => {
    connected.value = navigator.onLine
    if (!connected.value) cancel()
  }
  onMounted(() => {
    document.addEventListener('visibilitychange', visibilityChanged)
    window.addEventListener('online', connectivityChanged)
    window.addEventListener('offline', connectivityChanged)
    refreshTimer = window.setInterval(() => {
      if (autoRefresh.value && visible.value && connected.value && !busy.value && canAutoRefresh()) refresh()
    }, 10000)
  })
  onUnmounted(() => {
    cancel()
    window.clearInterval(refreshTimer)
    document.removeEventListener('visibilitychange', visibilityChanged)
    window.removeEventListener('online', connectivityChanged)
    window.removeEventListener('offline', connectivityChanged)
  })
  return { busy, error, lastFetch, autoRefresh, visible, connected, run, cancel }
}

export function downloadLogText(content: string, filename: string) {
  downloadLogBlob(new Blob([content], { type: 'text/plain;charset=utf-8' }), filename)
}

export function downloadLogBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename.replace(/[\\/:*?"<>|]/g, '_')
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
