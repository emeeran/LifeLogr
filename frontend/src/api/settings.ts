import { request } from './client'

export interface AISettings {
  ollama_model: string
  ollama_base_url: string
  ollama_embed_model: string
  enable_embeddings: boolean
  enable_tag_suggestions: boolean
  enable_sentiment: boolean
  enable_summarization: boolean
  enable_reflection_prompts: boolean
  enable_writer_block_helper: boolean
}

export interface StorageInfo {
  db_size_bytes: number
  media_count: number
  media_size_bytes: number
  entry_count: number
}

export interface WeatherSettings {
  enabled: boolean
}

export interface MapSettings {
  /** Opt-in online basemap tiles (OpenStreetMap) for the map view. */
  online_tiles: boolean
}

export interface SecuritySettings {
  /** Attachments of encrypted items are encrypted at rest (ENCRYPT_MEDIA). */
  media_encryption_enabled: boolean
  /** ISO timestamp of the last recovery-kit export ('' = never). */
  recovery_kit_exported_at: string
}

export interface AppSettings {
  ai: AISettings
  weather: WeatherSettings
  map: MapSettings
  security: SecuritySettings
  storage: StorageInfo
  version: string
  app_name: string
}

export interface AIModelInfo {
  name: string
  size: number
}

export interface StoragePathInfo {
  data_dir: string
  db_path: string
  db_size_bytes: number
  media_size_bytes: number
}

export interface RelocateResult {
  status: string
  old_path: string
  new_path: string
  copied_bytes: number
}

export const getSettings = () => request<AppSettings>('/settings')

export const updateSettings = (data: {
  ai?: Partial<AISettings>
  weather?: Partial<WeatherSettings>
  map?: Partial<MapSettings>
  /** Explicit consent required by the backend when ollama_base_url is non-loopback. */
  confirm_remote?: boolean
}) =>
  request<{ status: string }>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  })

export const getOllamaModels = () => request<AIModelInfo[]>('/settings/models')

export const vacuumDatabase = () =>
  request<{ status: string; reclaimed_bytes: number }>('/settings/vacuum', {
    method: 'POST',
  })

export interface EncryptMediaReport {
  dry_run: boolean
  candidates: number
  plaintext_bytes: number
  stale_thumbs: number
  updated: number
  thumbs_purged: number
  errors: string[]
}

/** Encrypt existing attachments of encrypted items (dry run by default). */
export const encryptMedia = (dryRun: boolean) =>
  request<EncryptMediaReport>(`/settings/encrypt-media?dry_run=${dryRun}`, {
    method: 'POST',
  })

// ── Recovery kit ─────────────────────────────────────────────────────────────

export interface RecoveryKitExportResult {
  /** The kit document — save it as lifelogr-recovery.json. */
  kit: Record<string, unknown>
  /** Present when no passphrase was given: the one-time code that opens the kit. */
  code: string | null
}

export interface RecoveryKitImportResult {
  status: 'restored' | 'unchanged' | 'confirm_replace'
  probes: { credentials: string; media: string }
}

export const exportRecoveryKit = (passphrase?: string) =>
  request<RecoveryKitExportResult>('/settings/recovery-kit/export', {
    method: 'POST',
    body: JSON.stringify({ passphrase: passphrase || null }),
  })

export const importRecoveryKit = (
  kit: Record<string, unknown>,
  passphrase: string,
  confirmReplace = false,
) =>
  request<RecoveryKitImportResult>('/settings/recovery-kit/import', {
    method: 'POST',
    body: JSON.stringify({
      kit,
      passphrase,
      confirm_replace: confirmReplace,
    }),
  })

export const getStoragePath = () =>
  request<StoragePathInfo>('/settings/storage-path')

export const updateStoragePath = (data_dir: string) =>
  request<RelocateResult>('/settings/storage-path', {
    method: 'POST',
    body: JSON.stringify({ data_dir }),
  })
