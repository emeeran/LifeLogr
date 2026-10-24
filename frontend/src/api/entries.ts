import { request, UPLOAD_TIMEOUT_MS, API_ORIGIN } from './client'
import type {
  EntryResponse,
  EntryListResponse,
  EntryCreate,
  EntryUpdate,
  EntryListParams,
  CalendarEntryResponse,
} from '../types'

export const entriesApi = {
  create(data: EntryCreate): Promise<EntryResponse> {
    return request('/entries', { method: 'POST', body: JSON.stringify(data) })
  },

  get(id: number): Promise<EntryResponse> {
    return request(`/entries/${id}`)
  },

  list(params?: EntryListParams): Promise<EntryListResponse> {
    const sp = new URLSearchParams()
    if (params?.offset != null) sp.set('offset', String(params.offset))
    if (params?.limit != null) sp.set('limit', String(params.limit))
    if (params?.tag_ids?.length)
      sp.set('tag_ids', params.tag_ids.join(','))
    if (params?.year) sp.set('year', String(params.year))
    if (params?.month) sp.set('month', String(params.month))
    if (params?.template_id != null)
      sp.set('template_id', String(params.template_id))
    const qs = sp.toString()
    return request(`/entries${qs ? `?${qs}` : ''}`)
  },

  update(id: number, data: EntryUpdate): Promise<EntryResponse> {
    return request(`/entries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  delete(id: number): Promise<void> {
    return request(`/entries/${id}`, { method: 'DELETE' })
  },

  importEntries(
    entries: { entry_date: string; title?: string; body: string }[],
  ): Promise<{ imported: number; skipped: number }> {
    return request('/entries/import', {
      method: 'POST',
      body: JSON.stringify(entries),
    })
  },

  importFile(file: File): Promise<{ imported: number; skipped: number }> {
    const form = new FormData()
    form.append('file', file)
    // Large imports can take minutes — the request-level timeout is raised to match.
    return request('/entries/import/file', {
      method: 'POST',
      body: form,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    })
  },

  resetDatabase(confirm: string): Promise<{ status: string; message: string }> {
    return request('/entries/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm }),
    })
  },

  deduplicate(): Promise<{ groups_found: number; duplicates_removed: number }> {
    return request('/entries/deduplicate', { method: 'POST' })
  },

  calendarMonth(year: number, month: number): Promise<CalendarEntryResponse[]> {
    return request(`/entries/calendar/${year}/${month}`)
  },

  search(query: string, offset = 0, limit = 20): Promise<EntryListResponse> {
    return request(
      `/entries/search?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`,
    )
  },

  exportMarkdownUrl(startDate?: string, endDate?: string): string {
    const sp = new URLSearchParams()
    if (startDate) sp.set('start_date', startDate)
    if (endDate) sp.set('end_date', endDate)
    const qs = sp.toString()
    return `${API_ORIGIN}/api/v1/entries/export/markdown${qs ? `?${qs}` : ''}`
  },

  exportJsonUrl(startDate?: string, endDate?: string): string {
    const sp = new URLSearchParams()
    if (startDate) sp.set('start_date', startDate)
    if (endDate) sp.set('end_date', endDate)
    const qs = sp.toString()
    return `${API_ORIGIN}/api/v1/entries/export/json${qs ? `?${qs}` : ''}`
  },
}
