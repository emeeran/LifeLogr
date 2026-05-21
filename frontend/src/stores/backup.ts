import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { BackupConfigResponse, BackupSnapshotResponse } from '../types'
import { backupApi } from '../api/backup'

export const useBackupStore = defineStore('backup', () => {
  const configs = ref<BackupConfigResponse[]>([])
  const snapshots = ref<BackupSnapshotResponse[]>([])
  const loading = ref(false)
  const lastBackupResult = ref<BackupSnapshotResponse | null>(null)
  const lastRestoreResult = ref<Record<string, unknown> | null>(null)

  async function fetchConfigs() {
    loading.value = true
    try {
      configs.value = await backupApi.getConfigs()
    } finally {
      loading.value = false
    }
  }

  async function fetchSnapshots(configId?: number) {
    const res = await backupApi.listSnapshots(configId)
    snapshots.value = res.items
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
    await backupApi.deleteConfig(configId)
    await fetchConfigs()
  }

  return {
    configs, snapshots, loading, lastBackupResult, lastRestoreResult,
    fetchConfigs, fetchSnapshots, runBackup, restore, deleteConfig,
  }
})
