// Google Calendar + Tasks two-way sync (mail stays on IMAP). Mirrors the
// backup.ts OAuth-connect pattern: getAuthUrl → window.open the consent URL;
// the loopback /callback stores the connection, then we poll /status.
import { request } from "./client";

export interface GoogleSyncStatus {
  connected: boolean;
  google_email?: string | null;
  calendar_enabled?: boolean;
  tasks_enabled?: boolean;
  contacts_enabled?: boolean;
  last_synced_at?: string | null;
  last_sync_error?: string | null;
}

export const googleSyncApi = {
  /** Consent URL for the calendar+tasks OAuth scopes. */
  getAuthUrl(): Promise<{ auth_url: string }> {
    return request("/google/auth-url");
  },

  getStatus(): Promise<GoogleSyncStatus> {
    return request("/google/status");
  },

  /** Run a two-way Calendar+Tasks+Contacts sync immediately. */
  sync(): Promise<{
    calendar?: Record<string, unknown> | null;
    tasks?: Record<string, unknown> | null;
    contacts?: Record<string, unknown> | null;
  }> {
    return request("/google/sync", { method: "POST" });
  },

  setToggles(toggles: {
    calendar_enabled?: boolean;
    tasks_enabled?: boolean;
    contacts_enabled?: boolean;
  }): Promise<{
    calendar_enabled: boolean;
    tasks_enabled: boolean;
    contacts_enabled: boolean;
  }> {
    return request("/google", { method: "PATCH", body: JSON.stringify(toggles) });
  },

  disconnect(): Promise<{ disconnected: boolean }> {
    return request("/google", { method: "DELETE" });
  },

  /** The "one go" button: IMAP mail + Google Calendar + Tasks. */
  syncAll(): Promise<{
    mail?: Record<string, unknown>;
    google?: Record<string, unknown>;
  }> {
    return request("/sync/all", { method: "POST" });
  },
};
