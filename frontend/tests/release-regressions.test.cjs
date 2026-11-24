const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const ts = require('typescript')
const vue = require('vue')
const { parse } = require('@vue/compiler-sfc')
const { renderToString } = require('vue/server-renderer')

const sourceRoot = path.resolve(__dirname, '../src')
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await vue.nextTick() }

// Exercise the actual SFC setup and shared request helpers with controlled I/O.
function harness() {
  let now = 0
  let nextTimer = 0
  const timers = new Map()
  const intervals = new Set()
  const unmounted = []
  const scope = vue.effectScope()
  const cache = new Map()
  const posts = []
  const gets = []
  const messages = []
  const downloads = []
  const route = vue.reactive({ params: { id: 'DEV-A' } })
  const store = vue.reactive({ currentDevice: { device_id: 'DEV-A', name: 'saved', location: 'site', group: 'group', is_online: true } })
  const releaseStore = vue.reactive({ info: null, loading: false, unavailable: false, async load() {}, async apply() {} })
  const io = {
    post: async () => ({ task_id: 'uuid-task', message: 'created' }),
    patch: async () => ({}),
    get: async () => ({ status: 'completed', result: { content: 'fresh', returned_lines: 1, total_lines: 1, truncated: false } }),
  }
  const setTimer = (callback, delay) => { const id = ++nextTimer; timers.set(id, { at: now + delay, callback }); return id }
  const clearTimer = id => timers.delete(id)
  const request = {
    post: (url, body, config) => { posts.push({ url, body, config }); return io.post(url, body, config) },
    patch: (url, body) => io.patch(url, body),
    get: (url, config) => { gets.push({ url, config }); return io.get(url, config) },
  }
  const events = { addEventListener() {}, removeEventListener() {} }
  let alert
  const mocks = {
    vue: { ...vue, onMounted() {}, onUnmounted: callback => unmounted.push(callback) },
    'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) },
    '@/api/auth': { getStoredUser: () => ({ is_staff: true }) },
    '@/stores/platformRelease': {
      isUpdateRunning: job => !!job && ['queued', 'preparing', 'switching', 'rolling_back'].includes(job.status),
      usePlatformRelease: () => releaseStore,
    },
    '@element-plus/icons-vue': {},
    'element-plus': {
      ElMessage: Object.fromEntries(['success', 'error', 'warning', 'info'].map(level => [level, message => messages.push({ level, message })])),
      ElMessageBox: { confirm: async () => {}, alert: (message, _title, options) => { alert = { message, options } } },
    },
    '@/stores/device': { useDeviceStore: () => store },
    '@/utils/deviceStatus': { isDeviceCurrentlyOnline: device => device.is_online },
  }
  function load(file, expose) {
    if (cache.has(file)) return cache.get(file)
    const text = fs.readFileSync(path.join(sourceRoot, file), 'utf8')
    const source = file.endsWith('.vue') ? parse(text).descriptor.scriptSetup.content : text
    const code = ts.transpileModule(source + (expose ? `\nexports.probe = { ${expose} };` : ''), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const module = { exports: {} }
    const context = {
      module, exports: module.exports,
      require(id) {
        if (mocks[id]) return mocks[id]
        if (id === './request') return request
        if (id.startsWith('@/')) {
          const local = id.slice(2)
          return local.endsWith('.vue') ? {} : load(`${local}.ts`)
        }
        return require(id)
      },
      window: { ...events, setTimeout: setTimer, clearTimeout: clearTimer, setInterval: () => { const id = ++nextTimer; intervals.add(id); return id }, clearInterval: id => intervals.delete(id) },
      document: { ...events, hidden: false, createElement: () => ({ click() { downloads.push(this.download) } }) },
      navigator: { onLine: true },
      localStorage: { getItem: () => null },
      URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL() {} },
      setTimeout: setTimer, clearTimeout: clearTimer, setInterval: () => ++nextTimer, clearInterval() {},
      AbortController, DOMException, Blob, atob, Error, console,
    }
    scope.run(() => vm.runInNewContext(code, context, { filename: file }))
    cache.set(file, module.exports)
    return module.exports
  }
  const detail = () => load('views/DeviceDetail.vue', [
    'showLogsCenterDialog', 'logTree', 'logLines', 'logContent', 'logTruncated', 'logTaskBusy', 'logTaskError',
    'loadLogContent', 'loadLogDates', 'handleSearchLogs', 'handleDownloadLog', 'searchResults', 'logSearchKeyword',
    'showEditDialog', 'editForm', 'deviceGroup', 'deviceGroupDirty', 'handleGroupChange', 'viewConfigDetail',
  ].join(',')).probe
  return {
    io, posts, gets, store, route, messages, downloads, detail, load, mocks, releaseStore,
    get alert() { return alert }, get now() { return now },
    async open() { const page = detail(); page.logTree.value = [{ id: 'cached' }]; page.showLogsCenterDialog.value = true; await flush(); return page },
    async advance(ms) {
      const target = now + ms
      await flush()
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        now = next[1].at; timers.delete(next[0]); next[1].callback(); await flush()
      }
      now = target; await flush()
    },
    dispose() { for (const callback of unmounted) callback(); scope.stop() },
  }
}

test('platform update progress exposes truthful preparation, switch and rollback stages', t => {
  const app = harness(); t.after(() => app.dispose())
  const { getUpdateProgress } = app.load('views/PlatformSettings.vue', 'getUpdateProgress').probe
  const template = parse(fs.readFileSync(path.join(sourceRoot, 'views/PlatformSettings.vue'), 'utf8')).descriptor.template.content

  assert.equal(JSON.stringify(getUpdateProgress({ status: 'queued' })), JSON.stringify({
    activeStep: 0, title: '更新任务已排队', detail: '宿主机更新器即将开始处理。', downloading: false, downloadPercent: 0,
  }))
  assert.equal(JSON.stringify(getUpdateProgress({ status: 'preparing' })), JSON.stringify({
    activeStep: 0,
    title: '正在准备更新',
    detail: '正在准备发布镜像，随后会预检数据库迁移。此阶段旧版平台继续运行。',
    downloading: false,
    downloadPercent: 0,
  }))
  assert.equal(JSON.stringify(getUpdateProgress({
    status: 'preparing', phase: 'download', downloaded_bytes: 45_000_000, total_bytes: 90_000_000,
    download_percent: 50, download_speed_bytes_per_second: 128_000, download_idle_seconds: 18,
  })), JSON.stringify({
    activeStep: 0,
    title: '正在下载发布镜像',
    detail: '正在准备发布镜像，随后会预检数据库迁移。此阶段旧版平台继续运行。',
    downloading: true,
    downloadPercent: 50,
  }))
  assert.equal(JSON.stringify(getUpdateProgress({ status: 'switching' })), JSON.stringify({
    activeStep: 2,
    title: '正在切换平台服务',
    detail: '镜像与数据库预检已通过，正在备份数据库、切换应用容器并等待健康检查。此阶段服务可能短暂中断。',
    downloading: false,
    downloadPercent: 0,
  }))
  assert.equal(JSON.stringify(getUpdateProgress({ status: 'rolling_back' })), JSON.stringify({
    activeStep: 2,
    title: '正在恢复上一版本',
    detail: '新版本未通过健康检查，正在恢复原应用容器和数据库。请保持页面打开，等待恢复结果。',
    downloading: false,
    downloadPercent: 0,
  }))
  assert.match(template, /title="下载并校验镜像"/)
  assert.match(template, /title="切换并验证"/)
  assert.match(template, /role="progressbar"/)
  assert.match(template, /:percentage="progress\.downloadPercent"/)
  assert.match(template, /downloaded_bytes/)
  assert.match(template, /download_speed_bytes_per_second/)
  assert.match(template, /download_idle_seconds/)
  assert.match(template, /阶段开始于/)
})

test('FRP public access is separate from the remote loopback management tunnel', () => {
  const page = fs.readFileSync(path.join(sourceRoot, 'views/FrpManage.vue'), 'utf8')
  const detail = fs.readFileSync(path.join(sourceRoot, 'views/DeviceDetail.vue'), 'utf8')
  const updater = fs.readFileSync(path.resolve(__dirname, '../../deployment/updater/daemon.py'), 'utf8')
  const backend = fs.readFileSync(path.resolve(__dirname, '../../server/management/views.py'), 'utf8')

  assert.match(page, /label="公网直连"/)
  assert.match(page, /关闭公网直连不会关闭 FRP 隧道；仍可通过 jetson_remote 经 212 回环转发管理设备。/)
  assert.match(page, /setFrpPublicAccess\(row\.device_id, enabled\)/)
  assert.match(page, /row\.frp_public_access && row\.ssh_connection_string/)
  assert.match(detail, /device\.frp_public_access && device\.web_access_url/)
  assert.match(detail, /公网直连已关闭，请通过 jetson_remote 管理隧道访问/)
  assert.match(updater, /"!", "-i", "lo"/)
  assert.match(updater, /action = "ACCEPT" if public_access else "DROP"/)
  assert.match(backend, /def plan_frp_port_assignments\(frp_config\):[\s\S]*?Keep every stored pair fixed/)
})

test('configuration history renders untrusted keys and values as text', async t => {
  const app = harness(); t.after(() => app.dispose())
  const config = { cameras: { '<img src=x onerror=alert(1)>': '192.0.2.1' }, note: '</pre><script>alert(1)</script>' }
  app.detail().viewConfigDetail({ config_data: config })
  assert.equal(app.alert.options.dangerouslyUseHTMLString, undefined)
  assert.equal(app.alert.message.type, 'pre')
  assert.equal(app.alert.message.children, JSON.stringify(config, null, 2))
  const html = await renderToString(app.alert.message)
  assert.ok(html.includes('&lt;img'))
  assert.ok(!html.includes('<img') && !html.includes('<script>'))
})

test('resource refresh preserves open edit and group drafts; reopening uses fresh values', async t => {
  const app = harness(); t.after(() => app.dispose())
  const page = app.detail()
  page.showEditDialog.value = true; await flush()
  page.editForm.value = { name: 'draft', location: 'draft-site' }
  page.deviceGroup.value = 'draft-group'; page.deviceGroupDirty.value = true
  app.store.currentDevice = { ...app.store.currentDevice, cpu_usage: 60, name: 'server-new' }; await flush()
  assert.equal(page.editForm.value.name, 'draft')
  assert.equal(page.editForm.value.location, 'draft-site')
  assert.equal(page.deviceGroup.value, 'draft-group')
  app.io.patch = async () => { throw new Error('save failed') }
  await page.handleGroupChange()
  app.store.currentDevice = { ...app.store.currentDevice, cpu_usage: 70 }; await flush()
  assert.equal(page.deviceGroup.value, 'draft-group')
  page.showEditDialog.value = false; await flush(); page.showEditDialog.value = true; await flush()
  assert.equal(page.editForm.value.name, 'server-new')
  app.io.patch = async () => ({})
  await page.handleGroupChange()
  assert.equal(page.deviceGroupDirty.value, false)
})

test('task details track the selected ID across completed and failed refreshes', async t => {
  const app = harness(); t.after(() => app.dispose())
  let rows = [{ id: 1, status: 'pending', progress: 0 }]
  app.mocks['@/api/project'] = { getProjectDeployments: async () => ({ results: rows }) }
  const page = app.load('views/TaskManage.vue', 'loadDeployments,viewDetail,currentDeployment,deployments').probe
  await page.loadDeployments(); page.viewDetail(page.deployments.value[0])
  rows = [{ id: 2, status: 'pending' }, { id: 1, status: 'completed', progress: 100 }]
  await page.loadDeployments()
  assert.equal(page.currentDeployment.value.status, 'completed')
  assert.equal(page.currentDeployment.value.progress, 100)
  rows = [{ id: 1, status: 'failed', progress: 20, error_message: 'synthetic failure' }]
  await page.loadDeployments()
  assert.equal(page.currentDeployment.value.error_message, 'synthetic failure')
})

test('log reads clamp the line budget and preserve numeric and UUID task IDs', async t => {
  for (const taskId of [1700000000001, 'synthetic-uuid']) {
    const app = harness(); t.after(() => app.dispose())
    app.io.post = async () => ({ task_id: taskId })
    const page = await app.open()
    page.logLines.value = 10000
    await page.loadLogContent('2026-11-18', 'synthetic.log')
    assert.equal(app.posts[0].body.lines, 2000)
    assert.equal(app.gets[0].config.params.task_id, taskId)
    assert.equal(app.posts[0].config.signal, app.gets[0].config.signal)
    assert.equal(page.logContent.value, 'fresh')
    page.logLines.value = -1
    await page.loadLogContent('2026-11-18', 'synthetic.log')
    assert.equal(app.posts[1].body.lines, 1)
  }
})

test('a task completing at 11 seconds succeeds and reports truncation', async t => {
  const app = harness(); t.after(() => app.dispose())
  app.io.get = async () => app.now < 11000 ? { status: 'processing' } : {
    status: 'completed', result: { content: 'slow result', returned_lines: 2000, total_lines: 2500, truncated: true },
  }
  const page = await app.open()
  const pending = page.loadLogContent('2026-11-18', 'synthetic.log')
  await app.advance(10000)
  assert.equal(page.logTaskBusy.value, true)
  assert.equal(page.logTaskError.value, '')
  await app.advance(1000); await pending
  assert.equal(page.logContent.value, 'slow result')
  assert.equal(page.logTruncated.value, true)
  assert.equal(page.logTaskBusy.value, false)
})

test('60-second deadline also bounds task creation and discards its late response', async t => {
  const app = harness(); t.after(() => app.dispose())
  let finish
  app.io.post = () => new Promise(resolve => { finish = resolve })
  const page = await app.open()
  const pending = page.loadLogContent('2026-11-18', 'synthetic.log')
  await app.advance(60000); await pending
  assert.equal(page.logTaskBusy.value, false)
  assert.match(page.logTaskError.value, /60/)
  assert.equal(app.posts[0].config.signal.aborted, true)
  finish({ task_id: 'late-task' }); await flush()
  assert.equal(app.gets.length, 0)
  assert.equal(page.logContent.value, '')
})

for (const boundary of ['close', 'route', 'device', 'unmount']) {
  test(`${boundary} cancels an outstanding poll without stale content or success messages`, async t => {
    const app = harness(); t.after(() => app.dispose())
    let finish
    app.io.get = () => new Promise(resolve => { finish = resolve })
    const page = await app.open()
    const pending = page.loadLogContent('2026-11-18', 'synthetic.log'); await flush()
    const signal = app.gets[0].config.signal
    if (boundary === 'close') page.showLogsCenterDialog.value = false
    if (boundary === 'route') app.route.params.id = 'DEV-B'
    if (boundary === 'device') app.store.currentDevice = { device_id: 'DEV-B', is_online: true }
    if (boundary === 'unmount') app.dispose()
    await flush(); await pending
    assert.equal(signal.aborted, true)
    finish({ status: 'completed', result: { content: 'stale', returned_lines: 1, total_lines: 1 } }); await flush()
    await app.advance(60000)
    assert.equal(page.logContent.value, '')
    assert.equal(page.logTaskBusy.value, false)
    assert.equal(page.logTaskError.value, '')
    assert.equal(app.gets.length, 1)
    assert.ok(app.gets[0].url.includes('/DEV-A/'))
    assert.equal(app.messages.length, 0)
  })
}

test('closing during creation never starts polling, and reopening permits retry', async t => {
  const app = harness(); t.after(() => app.dispose())
  let finish
  app.io.post = () => new Promise(resolve => { finish = resolve })
  const page = await app.open()
  const pending = page.loadLogContent('2026-11-18', 'synthetic.log'); await flush()
  page.showLogsCenterDialog.value = false; await flush(); await pending
  finish({ task_id: 'late-task' }); await flush()
  assert.equal(app.gets.length, 0)
  app.io.post = async () => ({ task_id: 'retry-task' })
  await app.open(); await page.loadLogContent('2026-11-18', 'synthetic.log')
  assert.equal(page.logContent.value, 'fresh')
})

test('switching files cancels old polling and late completion cannot replace the new file', async t => {
  const app = harness(); t.after(() => app.dispose())
  let finish
  app.io.post = async (_url, body) => ({ task_id: body.file })
  app.io.get = async (_url, config) => config.params.task_id === 'old.log'
    ? new Promise(resolve => { finish = resolve })
    : { status: 'completed', result: { content: 'new file', total_lines: 1, returned_lines: 1 } }
  const page = await app.open()
  const old = page.loadLogContent('2026-11-18', 'old.log'); await flush()
  await page.loadLogContent('2026-11-18', 'new.log'); await old
  finish({ status: 'completed', result: { content: 'old file' } }); await flush()
  assert.equal(app.gets[0].config.signal.aborted, true)
  assert.equal(page.logContent.value, 'new file')
  assert.equal(page.logTaskBusy.value, false)
})

test('failed log tasks show the server reason and a subsequent read can succeed', async t => {
  const app = harness(); t.after(() => app.dispose())
  app.io.get = async () => ({ status: 'failed', error_message: 'synthetic failure' })
  const page = await app.open()
  await page.loadLogContent('2026-11-18', 'synthetic.log')
  assert.equal(page.logTaskError.value, 'synthetic failure')
  assert.equal(page.logTaskBusy.value, false)
  app.io.get = async () => ({ status: 'completed', result: { content: 'retry', total_lines: 1, returned_lines: 1 } })
  await page.loadLogContent('2026-11-18', 'synthetic.log')
  assert.equal(page.logContent.value, 'retry')
  assert.equal(page.logTaskError.value, '')
})

test('list, search and ZIP download preserve the existing workflows', async t => {
  const app = harness(); t.after(() => app.dispose())
  app.io.post = async url => ({ task_id: url })
  app.io.get = async (_url, config) => {
    const id = config.params.task_id
    const result = id.endsWith('/list_logs/') ? { dates: ['2026-11-18'], files: { '2026-11-18': ['synthetic.log'] } }
      : id.endsWith('/search_logs/') ? { matches: [{ content: 'match' }], total_matches: 1, returned_matches: 1 }
        : id.endsWith('/download_log/') ? { content: Buffer.from('synthetic zip').toString('base64'), filename: 'synthetic.zip' }
          : { content: 'read', total_lines: 1, returned_lines: 1 }
    return { status: 'completed', result }
  }
  const page = await app.open()
  await page.loadLogDates()
  assert.equal(page.logTree.value[0].children[0].file, 'synthetic.log')
  page.logSearchKeyword.value = 'match'; await page.handleSearchLogs()
  assert.equal(page.searchResults.value.total_matches, 1)
  await page.loadLogContent('2026-11-18', 'synthetic.log')
  await page.handleDownloadLog()
  assert.deepEqual(app.downloads, ['synthetic.zip'])
})
