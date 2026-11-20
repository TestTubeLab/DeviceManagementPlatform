import request from './request'

export interface SshState {
  account: string
  independent_recovery_verified: boolean
  mode: 'legacy' | 'pending' | 'active' | 'rolled_back'
  local_password: 'enabled' | 'disabled' | 'unknown'
  frp_target: number | null
  remote_publickey_only: boolean
  host_fingerprints: string[]
  keys: { fingerprint: string; verified: boolean }[]
  pending_fingerprint: string | null
  pending_until: string | null
  login_observed: boolean
  error: string
}

export type SshAction =
  | { operation: 'add_key'; public_key: string }
  | { operation: 'activate' | 'confirm'; fingerprint: string; operator_verified: true }
  | { operation: 'verify_key' | 'remove_key'; fingerprint: string }

export interface SshManagement {
  enabled?: boolean
  enrolled: boolean
  online: boolean
  reported_at: string | null
  state: Partial<SshState>
  tasks: {
    id: string
    operation: SshAction['operation']
    status: 'pending' | 'processing' | 'completed' | 'failed' | 'expired'
    error: string
    fingerprint: string | null
  }[]
}

export function getSshManagement(id: string) {
  return request.get<unknown, SshManagement>(`/devices/${encodeURIComponent(id)}/ssh-management/`)
}

export function createSshTask(id: string, action: SshAction) {
  return request.post<unknown, { id: string; status: string }>(
    `/devices/${encodeURIComponent(id)}/ssh-management/tasks/`, action,
  )
}
