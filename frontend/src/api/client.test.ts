import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, formDataRequest, UPLOAD_TIMEOUT_MS } from './client'

/** Stub global fetch with a scripted response. */
function mockFetch(res: {
  status: number
  body?: string
  contentType?: string
}) {
  const fn = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(res.body ?? '', {
        status: res.status,
        headers: {
          'Content-Type': res.contentType ?? 'application/json',
        },
      }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => {
  vi.unstubAllGlobals()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request() error parsing', () => {
  it('throws an ApiError (not a string) with the backend detail', async () => {
    mockFetch({
      status: 401,
      body: JSON.stringify({ detail: 'API key not valid' }),
    })
    const err = await request('/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(401)
    expect(apiErr.detail).toBe('API key not valid')
    // .message stays human-readable so `errorMessage(e)` shows something useful.
    expect(apiErr.message).toBe('API key not valid')
    expect(apiErr.name).toBe('ApiError')
  })

  it('stringifies a structured (non-string) FastAPI detail', async () => {
    mockFetch({
      status: 422,
      body: JSON.stringify({
        detail: [{ loc: ['body', 'title'], msg: 'field required' }],
      }),
    })
    const err = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.detail).toContain('field required')
  })

  it('falls back to the raw body when it is not JSON', async () => {
    mockFetch({ status: 500, body: 'Internal Server Error' })
    const err = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(500)
    expect(err.detail).toBe('Internal Server Error')
    expect(err.message).toBe('Internal Server Error')
  })

  it('falls back to a generic message when the body is empty', async () => {
    mockFetch({ status: 503, body: '' })
    const err = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(503)
    expect(err.detail).toBe('')
    expect(err.message).toBe('Request failed (503)')
  })

  it('keeps a JSON error body whose detail is absent as raw text', async () => {
    mockFetch({ status: 409, body: JSON.stringify({ ok: false }) })
    const err = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(err.detail).toBe('{"ok":false}')
  })
})

describe('request() happy paths', () => {
  it('parses the JSON body on success', async () => {
    mockFetch({ status: 200, body: JSON.stringify({ id: 7 }) })
    await expect(request<{ id: number }>('/x')).resolves.toEqual({ id: 7 })
  })

  it('resolves undefined for 204 and sends JSON content type', async () => {
    const fetchFn = mockFetch({ status: 204, body: '' })
    await expect(request('/x', { method: 'DELETE' })).resolves.toBeUndefined()
    const init = fetchFn.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json',
    )
  })

  it('does not set Content-Type for FormData (browser sets the boundary)', async () => {
    const fetchFn = mockFetch({ status: 200, body: '{}' })
    const fd = new FormData()
    fd.append('file', new Blob(['x']), 'a.txt')
    await formDataRequest('/upload', fd)
    const init = fetchFn.mock.calls[0][1] as RequestInit
    expect(init.headers && (init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    // Uploads get the long timeout by default.
    expect(init.signal).toBeInstanceOf(AbortSignal)
    void UPLOAD_TIMEOUT_MS
  })
})
