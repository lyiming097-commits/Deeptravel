import { API_BASE_URL, STORAGE_KEYS } from './config'

function storedToken() {
  try {
    return uni.getStorageSync(STORAGE_KEYS.token) || ''
  } catch {
    return ''
  }
}

export function saveAuth(payload) {
  uni.setStorageSync(STORAGE_KEYS.token, payload.access_token || '')
  if (payload.user) uni.setStorageSync(STORAGE_KEYS.user, payload.user)
}

export function clearAuth() {
  uni.removeStorageSync(STORAGE_KEYS.token)
  uni.removeStorageSync(STORAGE_KEYS.user)
}

export function currentUser() {
  try {
    return uni.getStorageSync(STORAGE_KEYS.user) || null
  } catch {
    return null
  }
}

function apiUrl(path) {
  return `${API_BASE_URL}${path}`
}

function requestFailure(error, fallback = '网络连接失败') {
  const detail = String(error?.errMsg || '').trim()
  const localAddress = /^(https?:\/\/)?(127\.0\.0\.1|localhost|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i.test(API_BASE_URL)
  const accessHint = localAddress
    ? '请确认后端已启动且手机与电脑在同一网络'
    : '请确认后端和 Cloudflare Tunnel 仍在运行'
  if (/domain list|合法域名|不在.*域名|not in domain/i.test(detail)) {
    return new Error('微信未放行当前后端域名，请在开发者工具勾选“不校验合法域名”后重新真机调试')
  }
  if (/timeout/i.test(detail)) {
    return new Error(`连接后端超时（${API_BASE_URL}），${accessHint}`)
  }
  if (!detail || /request:fail|network error|connection refused/i.test(detail)) {
    return new Error(`无法连接后端（${API_BASE_URL}），${accessHint}`)
  }
  return new Error(detail || fallback)
}

export function request(path, options = {}) {
  const token = storedToken()
  const headers = {
    ...(options.header || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  return new Promise((resolve, reject) => {
    uni.request({
      url: apiUrl(path),
      method: options.method || 'GET',
      data: options.data,
      header: headers,
      timeout: options.timeout || 30000,
      responseType: options.responseType || 'text',
      success: (response) => {
        const body = response.data || {}
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(body)
          return
        }
        const detail = typeof body === 'string' ? body : body.detail
        reject(new Error(detail || `请求失败（HTTP ${response.statusCode}）`))
      },
      fail: (error) => reject(requestFailure(error)),
    })
  })
}

function decodeChunk(chunk, decoder) {
  if (typeof chunk === 'string') return chunk
  if (decoder) {
    try {
      return decoder.decode(chunk, { stream: true })
    } catch {
      // Fall back to the platform helper below.
    }
  }
  try {
    // TextDecoder is available in current微信基础库, but keep a small UTF-8
    // fallback for older Android WebViews.  Returning base64 here would make
    // SSE event delimiters invisible and silently lose Chinese tokens.
    const bytes = new Uint8Array(chunk)
    const encoded = Array.from(bytes)
      .map((value) => `%${value.toString(16).padStart(2, '0')}`)
      .join('')
    return decodeURIComponent(encoded)
  } catch {
    return ''
  }
}

function consumeSseFrame(frame, onEvent) {
  let eventName = 'message'
  const dataLines = []
  frame.split(/\r?\n/).forEach((line) => {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  })
  if (!dataLines.length) return
  let payload
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    // An incomplete frame is retained by the caller; malformed terminal
    // frames are ignored so one bad provider chunk cannot break the chat.
    return
  }
  onEvent(eventName, payload)
}

/**
 * Stream the backend SSE endpoint on platforms that expose
 * requestTask.onChunkReceived (微信基础库 2.11+).  Older clients fall back to
 * the ordinary JSON endpoint and still receive the complete grounded answer.
 */
export function streamMessage(sessionId, payload, onEvent) {
  const token = storedToken()
  return new Promise((resolve, reject) => {
    let buffer = ''
    let receivedChunk = false
    const decoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8') : null
    let settled = false
    const finish = (error, value) => {
      if (settled) return
      settled = true
      if (error) reject(error)
      else resolve(value)
    }
    let task = null
    const consumeSafely = (frame) => {
      try {
        consumeSseFrame(frame, onEvent)
        return true
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error || '对话处理失败')))
        task?.abort?.()
        return false
      }
    }
    task = uni.request({
      url: apiUrl(`/api/v1/chat/sessions/${sessionId}/messages/stream`),
      method: 'POST',
      data: payload,
      header: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      enableChunked: true,
      responseType: 'arraybuffer',
      timeout: 180000,
      success: (response) => {
        // If the platform did not expose chunks, the response is either the
        // full SSE body or an error. Parse it before falling back to JSON.
        if (response.statusCode < 200 || response.statusCode >= 300) {
          const body = response.data || {}
          finish(new Error(body.detail || `请求失败（HTTP ${response.statusCode}）`))
          return
        }
        if (!receivedChunk) {
          buffer += decodeChunk(response.data, decoder)
        }
        const frames = buffer.split(/\n\n/)
        buffer = frames.pop() || ''
        for (const frame of frames) {
          if (!consumeSafely(frame)) return
        }
        if (buffer.trim()) {
          if (!consumeSafely(buffer)) return
          buffer = ''
        }
        finish(null, true)
      },
      fail: (error) => finish(requestFailure(error, '流式请求失败')),
    })
    if (task && typeof task.onChunkReceived === 'function') {
      task.onChunkReceived((event) => {
        receivedChunk = true
        buffer += decodeChunk(event.data, decoder)
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          if (!consumeSafely(frame)) return
          boundary = buffer.indexOf('\n\n')
        }
      })
    }
  })
}
