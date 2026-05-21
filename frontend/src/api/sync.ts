import { request } from './client'
import type { SyncQueueItem, SyncStatusResponse, CloudSyncResponse } from '../types'

export const enqueueSync = (operation: string, entityType: string, entityId: number, payload: Record<string, unknown>) =>
  request<SyncQueueItem>('/sync/enqueue', { method: 'POST', body: JSON.stringify({ operation, entity_type: entityType, entity_id: entityId, payload }) })

export const getPending = (limit = 100) =>
  request<SyncQueueItem[]>(`/sync/pending?limit=${limit}`)

export const getSyncStatus = (provider = 'local') =>
  request<SyncStatusResponse>(`/sync/status?provider=${provider}`)

export const flushSync = (provider = 'local') =>
  request<{ synced: number; provider: string }>(`/sync/flush?provider=${provider}`, { method: 'POST' })

export const cloudPush = (provider: string, passphrase?: string) =>
  request<CloudSyncResponse>('/sync/cloud/push', { method: 'POST', body: JSON.stringify({ provider, passphrase }) })

export const cloudPull = (provider: string, passphrase?: string) =>
  request<CloudSyncResponse>('/sync/cloud/pull', { method: 'POST', body: JSON.stringify({ provider, passphrase }) })
