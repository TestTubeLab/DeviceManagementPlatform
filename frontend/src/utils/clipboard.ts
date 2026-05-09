export const copyToClipboard = async (text: string) => {
  if (!text) {
    throw new Error('empty text')
  }

  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'

  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()

  let copied = false

  try {
    copied = document.execCommand('copy')
  } finally {
    document.body.removeChild(textarea)
  }

  if (!copied) {
    throw new Error('copy failed')
  }
}
