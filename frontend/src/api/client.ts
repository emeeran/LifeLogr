// In Tauri desktop app, the frontend is served from tauri:// protocol (no Vite proxy).
// Detect this and use the backend's direct URL instead of relative paths.
const isTauri = !!(window as any).__TAURI_INTERNALS__
const API_ORIGIN = isTauri ? 'http://127.0.0.1:18765' : ''
const BASE_URL = `${API_ORIGIN}/api/v1`

// In Tauri, wait for the sidecar backend to be ready before making requests
let backendReady = !isTauri

async function waitForBackend(maxRetries = 30, delayMs = 500): Promise<void> {
  if (backendReady) return
  for (let i = 0; i < maxRetries; i++) {
    try {
      const res = await fetch(`${API_ORIGIN}/health`, { signal: AbortSignal.timeout(2000) })
      if (res.ok) {
        backendReady = true
        return
      }
    } catch { /* not ready yet */ }
    await new Promise(r => setTimeout(r, delayMs))
  }
  throw new Error('Backend failed to start')
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  await waitForBackend()
  const headers: Record<string, string> = { ...(options?.headers as Record<string, string>) }
  // Don't set Content-Type if body is FormData — let the browser set multipart boundary
  if (!headers['Content-Type'] && !(options?.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

function formDataRequest<T>(path: string, formData: FormData): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: formData,
  })
}

export { request, formDataRequest, API_ORIGIN }
