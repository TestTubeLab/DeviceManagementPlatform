const encoder = new TextEncoder()

function concat(...chunks: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(chunks.reduce((len, bytes) => len + bytes.length, 0))
  let offset = 0
  for (const bytes of chunks) {
    out.set(bytes, offset)
    offset += bytes.length
  }
  return out
}

function uint32(value: number): Uint8Array {
  const out = new Uint8Array(4)
  new DataView(out.buffer).setUint32(0, value)
  return out
}

function sshString(value: string | Uint8Array): Uint8Array {
  const bytes = typeof value === 'string' ? encoder.encode(value) : value
  return concat(uint32(bytes.length), bytes)
}

function decodeUrl(value: string | undefined): Uint8Array {
  if (!value) throw new Error('浏览器没有返回完整密钥')
  return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0))
}

function base64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
}

/** 在安全上下文生成一次性下载；只返回可上传的公钥。 */
export async function downloadNewSshKey(deviceId: string): Promise<string> {
  if (!window.isSecureContext || !crypto.subtle) {
    throw new Error('浏览器本地生成需要 HTTPS 安全上下文；也可以导入公钥')
  }
  const pair = await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify']) as CryptoKeyPair
  const privateJwk = await crypto.subtle.exportKey('jwk', pair.privateKey)
  const seed = decodeUrl(privateJwk.d)
  const pub = decodeUrl(privateJwk.x)
  if (seed.length !== 32 || pub.length !== 32) throw new Error('Ed25519 密钥长度不正确')

  const keyType = sshString('ssh-ed25519')
  const publicBlob = concat(keyType, sshString(pub))
  const tag = 'device-' + deviceId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 100)
  const check = crypto.getRandomValues(new Uint8Array(4))
  const privatePair = concat(seed, pub)
  seed.fill(0)
  // OpenSSH 明文容器：两份校验值、Ed25519 seed+公钥，以及 8 字节对齐填充。
  const section = concat(check, check, keyType, sshString(pub), sshString(privatePair), sshString(tag))
  privatePair.fill(0)
  const padding = Uint8Array.from({ length: (8 - section.length % 8) % 8 }, (_, i) => i + 1)
  const binary = concat(
    encoder.encode('openssh-key-v1\0'), sshString('none'), sshString('none'), sshString(''),
    uint32(1), sshString(publicBlob), sshString(concat(section, padding)),
  )
  section.fill(0)
  const lines = base64(binary).match(/.{1,70}/g)?.join('\n')
  binary.fill(0)
  const file = new Blob(
    [`-----BEGIN OPENSSH PRIVATE KEY-----\n${lines}\n-----END OPENSSH PRIVATE KEY-----\n`],
    { type: 'application/octet-stream' },
  )
  const url = URL.createObjectURL(file)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = `${tag}_ed25519`
    document.body.append(link)
    link.click()
    link.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return `ssh-ed25519 ${base64(publicBlob)} ${tag}`
}
