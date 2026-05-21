import { request } from './client'
import type { RevisionResponse, RevisionDiffResponse } from '../types'

export const listRevisions = (entryId: number, offset = 0, limit = 50) =>
  request<{ items: RevisionResponse[]; total: number; offset: number; limit: number }>(`/entries/${entryId}/revisions?offset=${offset}&limit=${limit}`)

export const getRevision = (entryId: number, revisionNumber: number) =>
  request<RevisionResponse>(`/entries/${entryId}/revisions/${revisionNumber}`)

export const diffRevisions = (entryId: number, fromRev: number, toRev: number) =>
  request<RevisionDiffResponse>(`/entries/${entryId}/revisions/${fromRev}/diff/${toRev}`)

export const restoreRevision = (entryId: number, revisionNumber: number) =>
  request<RevisionResponse>(`/entries/${entryId}/revisions/${revisionNumber}/restore`, { method: 'POST' })
