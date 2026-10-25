import { request, UPLOAD_TIMEOUT_MS } from './client'
import type {
  BackupConfigCreate,
  BackupConfigResponse,
  BackupSnapshotResponse,
} from '../types'

/** 202 body from an `as_job=true` data operation. */
export interface JobStartResponse {
  job_id: string
  kind: string
}

export const backupApi = {
  createConfig(data: BackupConfigCreate): Promise<BackupConfigResponse> {
    return request('/backup/config', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  getConfigs(): Promise<BackupConfigResponse[]> {
    return request('/backup/config')
  },

  testConnection(
    configId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request(`/backup/config/${configId}/test`, { method: 'POST' })
  },

  runBackup(configId: number): Promise<BackupSnapshotResponse> {
    return request('/backup/run', {
      method: 'POST',
      body: JSON.stringify({ config_id: configId }),
    })
  },

  /** Cloud backup as a polled job — poll `jobsApi.get(job_id)` for
   *  archive/upload progress; the job's terminal state carries the outcome. */
  runBackupJob(configId: number): Promise<JobStartResponse> {
    return request('/backup/run?as_job=true', {
      method: 'POST',
      body: JSON.stringify({ config_id: configId }),
    })
  },

  /** Cloud restore as a polled job (download/extract/swap progress). */
  restoreJob(configId: number): Promise<JobStartResponse> {
    return request('/backup/restore?as_job=true', {
      method: 'POST',
      body: JSON.stringify({ config_id: configId }),
    })
  },

  /** Scheduled-path "Run now" for a local folder, as a polled job. */
  runNowLocalJob(backupPath: string, retention: number): Promise<JobStartResponse> {
    return request(
      `/backup/run-now?as_job=true&backup_path=${encodeURIComponent(backupPath)}&retention=${retention}`,
      { method: 'POST' },
    )
  },

  listSnapshots(configId?: number, offset = 0, limit = 20) {
    const sp = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (configId != null) sp.set('config_id', String(configId))
    return request<{ items: BackupSnapshotResponse[]; total: number }>(
      `/backup/snapshots?${sp}`,
    )
  },

  restore(configId: number): Promise<Record<string, unknown>> {
    return request('/backup/restore', {
      method: 'POST',
      body: JSON.stringify({ config_id: configId }),
    })
  },

  deleteSnapshot(snapshotId: number): Promise<{
    deleted: boolean
    remote_file_deleted: boolean
    filename: string | null
  }> {
    return request(`/backup/snapshots/${snapshotId}`, { method: 'DELETE' })
  },

  deleteConfig(configId: number): Promise<void> {
    return request(`/backup/config/${configId}`, { method: 'DELETE' })
  },

  importLocal(
    file: File,
    opts?: { asJob?: boolean },
  ): Promise<{ success: boolean; restored: string[] } | JobStartResponse> {
    const fd = new FormData()
    fd.append('file', file)
    // A full-archive restore can be hundreds of MB — long timeout (see api/client).
    return request(opts?.asJob ? '/backup/import?as_job=true' : '/backup/import', {
      method: 'POST',
      body: fd,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    })
  },

  scheduleBackup(
    cron: string,
    opts?: { backupPath?: string; retention?: number; configId?: number },
  ): Promise<{
    job_id: string
    cron: string
    config_id: number | null
    next_run: string
  }> {
    const sp = new URLSearchParams({ cron })
    if (opts?.configId != null)
      sp.set('config_id', String(opts.configId))
    if (opts?.backupPath) sp.set('backup_path', opts.backupPath)
    if (opts?.retention) sp.set('retention', String(opts.retention))
    return request(`/backup/schedule?${sp}`, { method: 'POST' })
  },

  getScheduleStatus(): Promise<{
    running: boolean
    backup_scheduled: boolean
    next_run: string | null
  }> {
    return request('/backup/schedule/status')
  },

  /** The persisted schedule — source of truth for path/retention/cron. */
  getSchedule(): Promise<{
    configured: boolean
    cron: string | null
    config_id: number | null
    backup_path: string | null
    retention: number
    last_run: string | null
  }> {
    return request('/backup/schedule')
  },

  unscheduleBackup(): Promise<{ removed: boolean }> {
    return request('/backup/schedule', { method: 'DELETE' })
  },

  getGoogleDriveAuthUrl(): Promise<{ auth_url: string }> {
    return request('/backup/google-drive/auth-url')
  },

  getBoxAuthUrl(): Promise<{ auth_url: string }> {
    return request('/backup/box/auth-url')
  },
}
