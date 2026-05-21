import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as syncApi from '../api/sync'
import type { SyncStatusResponse } from '../types'

export const useSyncStore = defineStore('sync', () => {
  const status = ref<SyncStatusResponse | null>(null)
  const loading = ref(false)

  async function fetchStatus(provider = 'local') {
    loading.value = true
    try { status.value = await syncApi.getSyncStatus(provider) }
    finally { loading.value = false }
  }

  async function flush(provider = 'local') {
    await syncApi.flushSync(provider)
    await fetchStatus(provider)
  }

  async function push(provider: string, passphrase?: string) {
    const result = await syncApi.cloudPush(provider, passphrase)
    await fetchStatus(provider)
    return result
  }

  async function pull(provider: string, passphrase?: string) {
    const result = await syncApi.cloudPull(provider, passphrase)
    await fetchStatus(provider)
    return result
  }

  return { status, loading, fetchStatus, flush, push, pull }
})
