import { request } from './client'
import type { GlobalSearchResponse } from '../types'

export type SearchMode = 'keyword' | 'semantic' | 'hybrid'

export const globalSearch = (query: string, params?: { tag_ids?: string; date_from?: string; date_to?: string; offset?: number; limit?: number; mode?: SearchMode }) => {
  const sp = new URLSearchParams({ q: query })
  if (params?.tag_ids) sp.set('tag_ids', params.tag_ids)
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  if (params?.offset !== undefined) sp.set('offset', String(params.offset))
  if (params?.limit !== undefined) sp.set('limit', String(params.limit))
  if (params?.mode) sp.set('mode', params.mode)
  return request<GlobalSearchResponse>(`/search?${sp}`)
}
