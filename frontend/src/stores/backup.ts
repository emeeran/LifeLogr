import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { BackupConfigResponse, BackupSnapshotResponse } from '../types'
import { backupApi } from '../api/backup'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

export const useBackupStore = defineStore('backup', () => {
  const configs = shallowRef<BackupConfigResponse[]>([])
  const snapshots = shallowRef<BackupSnapshotResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastBackupResult = ref<BackupSnapshotResponse | null>(null)
  const lastRestoreResult = ref<Record<string, unknown> | null>(null)

  /** Set `error` + toast — the one place backup-store failures reach the user. */
  function fail(fallback: string, e: unknown) {
    const message = errorMessage(e) || fallback
    error.value = message
    useToastStore().error(`${fallback}: ${message}`)
  }

  async function fetchConfigs() {
    loading.value = true
    try {
      configs.value = await backupApi.getConfigs()
      error.value = null
    } catch (e: unknown) {
      fail('Failed to load backup configs', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchSnapshots(configId?: number) {
    try {
      const res = await backupApi.listSnapshots(configId)
      snapshots.value = res.items
      error.value = null
    } catch (e: unknown) {
      fail('Failed to load backups', e)
    }
  }

  async function runBackup(configId: number) {
    lastBackupResult.value = null
    const snapshot = await backupApi.runBackup(configId)
    lastBackupResult.value = snapshot
    // Refresh data
    await Promise.all([fetchConfigs(), fetchSnapshots()])
    return snapshot
  }

  async function restore(configId: number) {
    lastRestoreResult.value = null
    const result = await backupApi.restore(configId)
    lastRestoreResult.value = result
    return result
  }

  async function deleteConfig(configId: number) {
    try {
      await backupApi.deleteConfig(configId)
    } catch (e: unknown) {
      fail('Failed to delete backup config', e)
      throw e
    }
    await fetchConfigs()
  }

  return {
    configs,
    snapshots,
    loading,
    error,
    lastBackupResult,
    lastRestoreResult,
    fetchConfigs,
    fetchSnapshots,
    runBackup,
    restore,
    deleteConfig,
  }
})
