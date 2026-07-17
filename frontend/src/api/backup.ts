import { request, API_ORIGIN } from "./client";
import type {
  BackupConfigCreate,
  BackupConfigResponse,
  BackupSnapshotResponse,
} from "../types";

export const backupApi = {
  createConfig(data: BackupConfigCreate): Promise<BackupConfigResponse> {
    return request("/backup/config", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getConfigs(): Promise<BackupConfigResponse[]> {
    return request("/backup/config");
  },

  testConnection(
    configId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request(`/backup/config/${configId}/test`, { method: "POST" });
  },

  runBackup(configId: number): Promise<BackupSnapshotResponse> {
    return request("/backup/run", {
      method: "POST",
      body: JSON.stringify({ config_id: configId }),
    });
  },

  listSnapshots(configId?: number, offset = 0, limit = 20) {
    const sp = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (configId) sp.set("config_id", String(configId));
    return request<{ items: BackupSnapshotResponse[]; total: number }>(
      `/backup/snapshots?${sp}`,
    );
  },

  restore(configId: number): Promise<Record<string, unknown>> {
    return request("/backup/restore", {
      method: "POST",
      body: JSON.stringify({ config_id: configId }),
    });
  },

  deleteSnapshot(
    snapshotId: number,
  ): Promise<{
    deleted: boolean;
    remote_file_deleted: boolean;
    filename: string | null;
  }> {
    return request(`/backup/snapshots/${snapshotId}`, { method: "DELETE" });
  },

  deleteConfig(configId: number): Promise<void> {
    return request(`/backup/config/${configId}`, { method: "DELETE" });
  },

  exportLocal(): string {
    return `${API_ORIGIN}/api/v1/backup/export`;
  },

  async importLocal(
    file: File,
  ): Promise<{ success: boolean; restored: string[] }> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_ORIGIN}/api/v1/backup/import`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(`Import failed: ${res.status}`);
    return res.json();
  },

  scheduleBackup(
    cron: string,
    opts?: { backupPath?: string; retention?: number; configId?: number },
  ): Promise<{
    job_id: string;
    cron: string;
    config_id: number | null;
    next_run: string;
  }> {
    const sp = new URLSearchParams({ cron });
    if (opts?.configId) sp.set("config_id", String(opts.configId));
    if (opts?.backupPath) sp.set("backup_path", opts.backupPath);
    if (opts?.retention) sp.set("retention", String(opts.retention));
    return request(`/backup/schedule?${sp}`, { method: "POST" });
  },

  getScheduleStatus(): Promise<{
    running: boolean;
    backup_scheduled: boolean;
    next_run: string | null;
  }> {
    return request("/backup/schedule/status");
  },

  unscheduleBackup(): Promise<{ removed: boolean }> {
    return request("/backup/schedule", { method: "DELETE" });
  },

  getGoogleDriveAuthUrl(): Promise<{ auth_url: string }> {
    return request("/backup/google-drive/auth-url");
  },

  getBoxAuthUrl(): Promise<{ auth_url: string }> {
    return request("/backup/box/auth-url");
  },
};
