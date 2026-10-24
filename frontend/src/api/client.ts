// In Tauri desktop app, the frontend is served from tauri:// protocol (no Vite proxy).
// Detect this and use the backend's direct URL instead of relative paths.
const isTauri = '__TAURI_INTERNALS__' in window
const API_ORIGIN = isTauri ? 'http://127.0.0.1:18765' : ''
const BASE_URL = `${API_ORIGIN}/api/v1`

/** Default request timeout. Generous, but no request hangs forever. */
const DEFAULT_TIMEOUT_MS = 30_000
/** Uploads (media / backup import / entry import) can be large and slow. */
export const UPLOAD_TIMEOUT_MS = 300_000

// In Tauri, wait for the sidecar backend to be ready before making requests
let backendReady = !isTauri

async function waitForBackend(maxRetries = 30, delayMs = 500): Promise<void> {
  if (backendReady) return
  for (let i = 0; i < maxRetries; i++) {
    try {
      const res = await fetch(`${API_ORIGIN}/health`, {
        signal: AbortSignal.timeout(2000),
      })
      if (res.ok) {
        backendReady = true
        return
      }
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delayMs))
  }
  throw new Error('Backend failed to start')
}

/** Extract the backend's `detail` field from an error body — parsed once, here,
 *  so callers never regex raw `API 500: {"detail": …}` strings again. */
async function parseDetail(res: Response): Promise<string> {
  let body = ''
  try {
    body = await res.text()
  } catch {
    return ''
  }
  if (!body) return ''
  try {
    const parsed: unknown = JSON.parse(body)
    if (typeof parsed === 'string') return parsed
    if (parsed && typeof parsed === 'object') {
      const detail = (parsed as { detail?: unknown }).detail
      if (typeof detail === 'string') return detail
      if (detail != null) return JSON.stringify(detail)
    }
  } catch {
    /* body wasn't JSON — fall through to the raw text */
  }
  return body
}

/** Typed error for every non-2xx response `request()` sees.
 *  `detail` is the backend's message (parsed from the JSON body when possible);
 *  `message` is the human-readable form components can show directly. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export interface RequestOptions extends RequestInit {
  /** Abort the request after this many ms (default 30s). Pass a larger value
   *  (or `UPLOAD_TIMEOUT_MS`) for big uploads. */
  timeoutMs?: number
}

/**
 * POST/GET/… JSON transport used by every api/* module. Throws `ApiError`
 * (never a bare string) on non-2xx responses.
 */
async function request<T>(
  path: string,
  options?: RequestOptions,
  config?: { signal?: AbortSignal },
): Promise<T> {
  await waitForBackend()
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  }
  // Don't set Content-Type if body is FormData — let the browser set multipart boundary
  if (!headers['Content-Type'] && !(options?.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  // Combine the caller's signal (if any) with the timeout into one controller.
  const controller = new AbortController()
  const external = config?.signal ?? options?.signal ?? null
  const onAbort = () => controller.abort()
  if (external) {
    if (external.aborted) controller.abort()
    else external.addEventListener('abort', onAbort, { once: true })
  }
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const timer =
    timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    })
    if (!res.ok) throw new ApiError(res.status, await parseDetail(res))
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  } finally {
    if (timer) clearTimeout(timer)
    external?.removeEventListener('abort', onAbort)
  }
}

function formDataRequest<T>(path: string, formData: FormData): Promise<T> {
  // Multipart bodies are uploads — give them the long timeout by default.
  return request<T>(path, {
    method: 'POST',
    body: formData,
    timeoutMs: UPLOAD_TIMEOUT_MS,
  })
}

/** GET a binary payload (e.g. read-aloud audio) with the same error contract
 *  as `request()` — throws `ApiError` carrying the backend's `detail` instead
 *  of handing the caller a non-ok response to interpret. */
export async function blobRequest(path: string): Promise<Blob> {
  await waitForBackend()
  const res = await fetch(`${BASE_URL}${path}`, {
    signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
  })
  if (!res.ok) throw new ApiError(res.status, await parseDetail(res))
  return await res.blob()
}

export { request, formDataRequest, API_ORIGIN, isTauri }
