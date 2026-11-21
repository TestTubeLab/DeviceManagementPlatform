<template>
  <el-dialog
    :model-value="true"
    title="SSH 管理"
    width="min(750px, calc(100vw - 24px))"
    :before-close="close"
    :close-on-click-modal="false"
  >
    <el-alert
      v-if="loadFailed"
      title="无法读取 SSH 管理状态。请确认平台已启用、使用 HTTPS 且当前账号有管理权限。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-else-if="management?.enabled === false"
      title="平台尚未启用 SSH 管理。请联系平台管理员检查服务配置。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="windowLocationProtocol !== 'https:'"
      title="请打开管理平台的 HTTPS 入口并验证证书，再进行 SSH 管理。"
      type="warning"
      :closable="false"
    />
    <el-alert
      v-if="!loadFailed && management?.enrolled && !management.online"
      :title="management.reported_at ? 'SSH 管理 Agent 离线；以下是历史状态。' : '已签发设备凭据，等待 Agent 首次上报。'"
      type="warning"
      :closable="false"
    />
    <div v-loading="loading" class="ssh-details">
      <el-descriptions v-if="management && management.enabled !== false" :column="1" border>
        <el-descriptions-item label="设备 / 运维账号">{{ deviceId }} / {{ state.account || '-' }}</el-descriptions-item>
        <el-descriptions-item label="现场密码策略">{{ passwordText }}</el-descriptions-item>
        <el-descriptions-item label="FRP 端口">
          {{ externalPort ?? '未分配' }} → {{ state.frp_target ? '127.0.0.1:' + state.frp_target : '未确认目标' }}
        </el-descriptions-item>
        <el-descriptions-item label="远程模式">{{ modeText }}</el-descriptions-item>
        <el-descriptions-item label="主机公钥指纹">
          <code class="wrap">{{ state.host_fingerprints?.join(' / ') || '-' }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="上报时间">
          {{ management.reported_at ? new Date(management.reported_at).toLocaleString() : '-' }}
        </el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="state.error" :title="state.error" type="warning" :closable="false" />
      <el-alert
        v-if="management?.enabled && !management.enrolled && !management.enrollment_available"
        title="平台尚未配置网页签发。请在可信运维控制台签发设备凭据，并确认设备能访问加密入口。"
        type="warning"
        :closable="false"
      />
      <section v-if="enrollmentBundle || (management?.enrollment_available && !management.enrolled)" class="enrollment">
        <strong>{{ enrollmentBundle ? '纳管文件已签发' : '设备尚未纳管' }}</strong>
        <p>通过可信安装方式交付 Agent 模块、平台 CA 和纳管文件。安装后等待设备上报，纳管不会自动改变 SSH 登录策略。</p>
        <el-input v-model="enrollmentAccount" :disabled="!!enrollmentBundle" placeholder="设备上已有的非 root 运维账号" />
        <el-button
          type="primary"
          :disabled="!enrollmentAccount.trim() || !!enrollmentBundle || submitting || windowLocationProtocol !== 'https:'"
          @click="createEnrollmentFile"
        >签发并下载一次性纳管文件</el-button>
        <el-button v-if="enrollmentBundle" @click="downloadEnrollmentFile">重新下载本次纳管文件</el-button>
      </section>
      <el-alert
        v-if="management?.online && state.mode !== 'active' && !state.independent_recovery_verified"
        title="设备尚未确认独立恢复入口，不能切换 FRP 的 SSH 认证。"
        type="info"
        :closable="false"
      />
      <el-alert
        v-if="state.pending_fingerprint"
        :title="state.login_observed ? '已观察到该公钥登录。确认你通过原 FRP 端口完成了新会话。' : '请用该公钥通过原 FRP 端口新开 SSH 会话。'"
        :description="state.pending_until ? '截止：' + new Date(state.pending_until).toLocaleTimeString() : undefined"
        type="info"
        :closable="false"
      />
      <el-button
        v-if="state.pending_fingerprint"
        :disabled="loadFailed || busy || !management?.online || !state.login_observed || !!state.error"
        type="primary"
        @click="confirmLogin"
      >确认已通过 FRP 登录</el-button>
      <el-input
        v-if="management?.enrolled"
        v-model="publicKey"
        :disabled="busy || !management.online"
        type="textarea"
        :rows="2"
        placeholder="粘贴单行 ssh-ed25519 公钥"
        aria-label="SSH 公钥"
      />
      <el-space v-if="management?.enrolled" wrap>
        <el-button :disabled="!canWrite || !publicKey.trim()" @click="addKey">添加公钥</el-button>
        <el-button :disabled="!canWrite" @click="generateKey">生成并下载私钥</el-button>
      </el-space>
      <el-table v-if="state.keys?.length" :data="state.keys" size="small">
        <el-table-column prop="fingerprint" label="授权公钥指纹" min-width="160" />
        <el-table-column label="验证" width="80">
          <template #default="{ row }">{{ row.verified ? '已验证' : '待试登' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="155">
          <template #default="{ row }">
            <el-button
              v-if="state.mode !== 'active'"
              link type="primary"
              :disabled="!canWrite || !!state.error || !externalPort || !state.independent_recovery_verified"
              @click="activate(row.fingerprint)"
            >启用仅公钥</el-button>
            <template v-else>
              <el-button link type="primary" :disabled="!canWrite || !!state.error"
                @click="submit({ operation: 'verify_key', fingerprint: row.fingerprint })">开始试登</el-button>
              <el-button link type="danger" :disabled="!canWrite || !!state.error || !hasOtherVerified(row.fingerprint)"
                @click="removeKey(row.fingerprint)">撤销</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-table v-if="management?.tasks.length" :data="management.tasks" size="small" max-height="190">
        <el-table-column label="操作记录" width="125">
          <template #default="{ row }">{{ operationText[row.operation as SshAction['operation']] }}</template>
        </el-table-column>
        <el-table-column label="任务状态" width="100">
          <template #default="{ row }">{{ taskText[row.status as SshManagement['tasks'][number]['status']] }}</template>
        </el-table-column>
        <el-table-column prop="error" label="失败原因" min-width="150" />
      </el-table>
    </div>
    <template #footer>
      <el-button :disabled="loading" @click="refresh">刷新</el-button>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createSshEnrollment, createSshTask, getSshManagement,
  type SshAction, type SshEnrollment, type SshManagement,
} from '@/api/deviceSsh'
import { downloadNewSshKey } from '@/utils/ed25519Download'

const props = defineProps<{ deviceId: string; externalPort: number | null }>()
const emit = defineEmits<{ close: [] }>()
const management = ref<SshManagement | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const submitting = ref(false)
const publicKey = ref('')
const enrollmentAccount = ref('')
const enrollmentBundle = ref<SshEnrollment | null>(null)
const windowLocationProtocol = window.location.protocol
let refreshTimer: ReturnType<typeof setInterval> | undefined
let mounted = false
const state = computed(() => management.value?.state ?? {})
const busy = computed(() => submitting.value || !!management.value?.tasks.some(
  task => task.status === 'pending' || task.status === 'processing',
))
const canWrite = computed(() => (
  !loadFailed.value && management.value?.online && !busy.value && !state.value.pending_fingerprint
))
const passwordText = computed(() => ({ enabled: '允许（现场入口配置未被修改）', disabled: '已禁用', unknown: '未确认' }
  [state.value.local_password ?? 'unknown']))
const modeText = computed(() => {
  if (state.value.mode === 'active') return state.value.remote_publickey_only ? '仅公钥' : '仅公钥策略已锁定，当前连接状态异常'
  if (state.value.mode === 'pending') return '待验证，超时自动回退'
  if (state.value.mode === 'rolled_back') return '已回退至原配置'
  return state.value.mode === 'legacy' ? '原有配置' : '未确认'
})
const operationText = {
  add_key: '添加公钥', activate: '启用仅公钥', verify_key: '开始试登', confirm: '确认试登', remove_key: '撤销公钥',
}
const taskText = { pending: '待领取', processing: '执行中', completed: '已完成', failed: '失败', expired: '已过期' }

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    management.value = await getSshManagement(props.deviceId)
    loadFailed.value = false
    if (mounted && management.value.enabled !== false && !refreshTimer) refreshTimer = setInterval(refresh, 5000)
  } catch {
    loadFailed.value = true
    clearInterval(refreshTimer)
    refreshTimer = undefined
  } finally {
    loading.value = false
  }
}

async function submit(action: SshAction) {
  if (loadFailed.value || busy.value || !management.value?.online) return false
  submitting.value = true
  try {
    await createSshTask(props.deviceId, action)
    await refresh()
    ElMessage.success('任务已下发，请等待设备回执')
    return true
  } catch {
    return false
  } finally {
    submitting.value = false
  }
}

async function addKey() {
  if (await submit({ operation: 'add_key', public_key: publicKey.value.trim() })) publicKey.value = ''
}

async function createEnrollmentFile() {
  if (submitting.value || loadFailed.value || !management.value?.enrollment_available) return
  try {
    await ElMessageBox.confirm(
      '平台不保存凭据明文，关闭此窗口后无法找回。请通过可信安装方式交付到对应设备；不要发送到聊天或普通文件共享。',
      '签发设备纳管文件',
      { type: 'warning', confirmButtonText: '签发并下载', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  if (submitting.value || enrollmentBundle.value) return
  submitting.value = true
  try {
    enrollmentBundle.value = await createSshEnrollment(props.deviceId, {
      account: enrollmentAccount.value.trim(),
      independent_recovery_verified: false,
    })
    downloadEnrollmentFile()
    await refresh()
  } catch (error) {
    const responseDetail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(responseDetail || '纳管文件签发失败，请检查 HTTPS、权限和平台配置')
  } finally {
    submitting.value = false
  }
}

function downloadEnrollmentFile() {
  if (!enrollmentBundle.value) return
  const blob = new Blob([JSON.stringify(enrollmentBundle.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${props.deviceId}-ssh-enrollment.json`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function generateKey() {
  try {
    await ElMessageBox.confirm(
      '私钥文件没有口令，拿到文件的人可使用它登录。请仅保存在信任的运维电脑，限制文件权限；平台无法找回。',
      '下载无口令私钥',
      { type: 'warning', confirmButtonText: '生成并下载', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    publicKey.value = await downloadNewSshKey(props.deviceId)
    ElMessage.success('已发起下载。确认私钥保存后，再点击添加公钥。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '浏览器不支持生成密钥，请导入公钥')
  }
}

async function activate(fingerprint: string) {
  try {
    await ElMessageBox.confirm(
      '当前 FRP 会话可能短暂中断。请先确认 212 跳板之外有独立恢复通道，原端口已限制来源。切换后用所选公钥新开会话，5 分钟内完成确认。',
      '切换为远程仅公钥',
      { type: 'warning', confirmButtonText: '已核验，切换', cancelButtonText: '取消' },
    )
    await submit({ operation: 'activate', fingerprint, operator_verified: true })
  } catch {
    // 用户取消。
  }
}

function confirmLogin() {
  if (state.value.pending_fingerprint) {
    return submit({ operation: 'confirm', fingerprint: state.value.pending_fingerprint, operator_verified: true })
  }
}

function hasOtherVerified(fingerprint: string) {
  return state.value.keys?.some(key => key.verified && key.fingerprint !== fingerprint)
}

async function removeKey(fingerprint: string) {
  try {
    await ElMessageBox.confirm(`撤销公钥 ${fingerprint}？已登录会话不受影响。`, '撤销公钥', { type: 'warning' })
    await submit({ operation: 'remove_key', fingerprint })
  } catch {
    // 用户取消。
  }
}

function close() {
  emit('close')
}

onMounted(() => {
  mounted = true
  void refresh()
})
onUnmounted(() => {
  mounted = false
  clearInterval(refreshTimer)
})
</script>

<style scoped>
.ssh-details {
  display: grid;
  gap: 12px;
  min-height: 42px;
}

.enrollment {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
}

.enrollment p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.wrap {
  overflow-wrap: anywhere;
}
</style>
