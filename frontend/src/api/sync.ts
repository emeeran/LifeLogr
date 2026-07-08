import { request } from './client'
import type { SyncStatusResponse, CloudSyncResponse } from '../types'

export const getSyncStatus = (provider = 'local') =>
  request<SyncStatusResponse>(`/sync/status?provider=${provider}`)

export const flushSync = (provider = 'local') =>
  request<{ synced: number; provider: string }>(`/sync/flush?provider=${provider}`, { method: 'POST' })

export const cloudPush = (provider: string, passphrase?: string) =>
  request<CloudSyncResponse>('/sync/cloud/push', { method: 'POST', body: JSON.stringify({ provider, passphrase }) })

export const cloudPull = (provider: string, passphrase?: string) =>
  request<CloudSyncResponse>('/sync/cloud/pull', { method: 'POST', body: JSON.stringify({ provider, passphrase }) })
