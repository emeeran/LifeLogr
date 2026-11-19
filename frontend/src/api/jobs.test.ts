import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { jobsApi } from './jobs'

/**
 * startExport() takes the api/*Url() builders' full `${origin}/api/v1/…`
 * URLs but calls request(), which adds the /api/v1 prefix itself — the
 * regression guard here pins the single-prefix contract (a doubled
 * /api/v1/api/v1/… path 404s on every job-based export).
 */

function mockFetch(res: { status: number; body?: string }) {
  const fn = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(res.body ?? '', {
        status: res.status,
        headers: { 'Content-Type': 'application/json' },
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

describe('jobsApi.startExport URL handling', () => {
  it('does not double the prefix when given a bare /api/v1 path', async () => {
    const fetchFn = mockFetch({
      status: 200,
      body: JSON.stringify({ job_id: 'j1', kind: 'export' }),
    })
    await jobsApi.startExport('/api/v1/entries/export/diarium-db')
    expect(fetchFn.mock.calls[0][0]).toBe(
      '/api/v1/entries/export/diarium-db?as_job=true',
    )
  })

  it('accepts builder-relative paths without a prefix', async () => {
    const fetchFn = mockFetch({
      status: 200,
      body: JSON.stringify({ job_id: 'j1', kind: 'export' }),
    })
    await jobsApi.startExport('/entries/export/markdown?start_date=2026-01-01')
    expect(fetchFn.mock.calls[0][0]).toBe(
      '/api/v1/entries/export/markdown?start_date=2026-01-01&as_job=true',
    )
  })
})
