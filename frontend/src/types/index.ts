export interface TagBrief {
  id: number
  name: string
}

export interface TagResponse {
  id: number
  name: string
  parent_id: number | null
  children: TagBrief[]
  entry_count: number
}

export interface TagCreate {
  name: string
  parent_id?: number | null
}

export interface TagUpdate {
  name: string
}

export interface EntryResponse {
  id: number
  entry_date: string
  title: string | null
  body: string
  summary: string | null
  is_deleted: boolean
  is_encrypted: boolean
  tags: TagBrief[]
  media_count: number
  has_recording: boolean
  created_at: string
  updated_at: string
}

export interface EntryListResponse {
  items: EntryResponse[]
  total: number
  offset: number
  limit: number
}

export interface EntryCreate {
  entry_date: string
  title?: string | null
  body: string
  tag_ids?: number[]
}

export interface EntryUpdate {
  title?: string | null
  body?: string | null
  tag_ids?: number[] | null
}

export interface MediaResponse {
  id: number
  entry_id: number
  filename: string
  media_type: string
  file_size: number
  caption: string | null
  created_at: string
}

export interface MediaTimelineItem extends MediaResponse {
  entry_date: string
  entry_title: string | null
}

export interface MediaTimelineResponse {
  items: MediaTimelineItem[]
  total: number
}

export interface VoiceRecordingResponse {
  id: number
  entry_id: number
  media_id: number
  duration_seconds: number
  audio_format: string
  transcription: string | null
  is_transcribed: boolean
  created_at: string
}

export interface BackupConfigCreate {
  provider: string
  credentials: Record<string, string>
  schedule_cron?: string | null
}

export interface BackupConfigResponse {
  id: number
  provider: string
  schedule_cron: string | null
  last_sync_at: string | null
  created_at: string
  updated_at: string
}

export interface BackupSnapshotResponse {
  id: number
  config_id: number
  status: string
  entries_synced: number
  media_synced: number
  started_at: string
  completed_at: string | null
  error_message: string | null
}

export interface PaginatedParams {
  offset?: number
  limit?: number
}

export interface EntryListParams extends PaginatedParams {
  tag_ids?: number[]
  year?: number
  month?: number
}

// ── AI (Ollama) ──────────────────────────────────────────────────────

export interface GrammarSuggestion {
  offset: number
  length: number
  original: string
  suggestion: string
  rule_id: string
  message: string
}

export interface GrammarCheckResponse {
  corrected_text: string
  suggestions: GrammarSuggestion[]
}

export interface SpellCheckResponse {
  corrected_text: string
  misspellings: GrammarSuggestion[]
}

export interface RewriteResponse {
  rewritten_text: string
  style: string
}

export interface AIStatusResponse {
  ollama_available: boolean
  model_name: string
  model_loaded: boolean
  embed_model_available: boolean
  error: string | null
}

// ── AI Tag Suggestions ──────────────────────────────────────────────

export interface TagSuggestionResponse {
  tags: string[]
}

// ── AI Writer's Block ───────────────────────────────────────────────

export interface ContinueWritingResponse {
  continuation: string
}

// ── AI Smart Tools ──────────────────────────────────────────────────

export interface ExpandResponse {
  expanded_text: string
}

export interface ChangeToneResponse {
  changed_text: string
  tone: string
}

// ── AI Analyze Text ──────────────────────────────────────────────────

export interface AnalyzeTextResponse {
  emotions: string[]
  themes: string[]
  summary: string
}

// ── AI Define Text ───────────────────────────────────────────────────

export interface DefineTextResponse {
  definition: string
}

// ── AI On This Day ──────────────────────────────────────────────────

export interface OnThisDayPastEntry {
  years_ago: number
  date: string
  title: string | null
  snippet: string | null
  entry_ids: number[]
}

export interface OnThisDayResponse {
  years_ago: number
  entries_count: number
  reflection: string
  past_entries: OnThisDayPastEntry[]
}

// ── AI Themes ───────────────────────────────────────────────────────

export interface ThemeInsight {
  theme: string
  frequency: string
  months_mentioned: string[]
  insight: string
}

export interface ThemesResponse {
  themes: ThemeInsight[]
}

// ── Encryption ───────────────────────────────────────────────────────

export interface EncryptionStatusResponse {
  entry_id: number
  is_encrypted: boolean
  encrypted_at: string | null
}

// ── Video Notes ──────────────────────────────────────────────────────

export interface VideoNoteResponse {
  id: number
  entry_id: number
  filename: string
  duration_seconds: number | null
  thumbnail_path: string | null
  transcription: string | null
  created_at: string
}

// ── Search (FTS5) ────────────────────────────────────────────────────

export interface SearchResultEntry {
  id: number
  entry_date: string
  title: string | null
  snippet: string
  rank: number
}

export interface GlobalSearchResponse {
  items: SearchResultEntry[]
  total: number
  offset: number
  limit: number
}

// ── Analytics ─────────────────────────────────────────────────────────

export interface OverviewResponse {
  total_entries: number
  total_words: number
  total_media: number
  total_recordings: number
  date_range_start: string | null
  date_range_end: string | null
  longest_streak: number
  current_streak: number
}

export interface WritingHabitResponse {
  day_of_week: number
  day_name: string
  entry_count: number
}

export interface WordCountResponse {
  total_words: number
  average_words_per_entry: number
  longest_entry_words: number
  shortest_entry_words: number
}

export interface TagStatsResponse {
  tag_id: number
  tag_name: string
  usage_count: number
}

export interface HeatmapDayResponse {
  date: string
  count: number
}

export interface HeatmapResponse {
  year: number
  days: HeatmapDayResponse[]
}

export interface MediaStatsResponse {
  total_images: number
  total_videos: number
  total_recordings: number
  total_size_bytes: number
}

// ── Reminders ────────────────────────────────────────────────────────

export interface ReminderResponse {
  id: number
  title: string
  message: string | null
  reminder_time: string
  days_of_week: string
  is_active: boolean
  last_fired_at: string | null
  created_at: string
  updated_at: string
}

export interface ReminderCreate {
  title: string
  message?: string | null
  reminder_time: string
  days_of_week?: string
  is_active?: boolean
}

export interface ReminderUpdate {
  title?: string | null
  message?: string | null
  reminder_time?: string | null
  days_of_week?: string | null
  is_active?: boolean | null
}

// ── Sync ─────────────────────────────────────────────────────────────

export interface SyncQueueItem {
  id: number
  operation: string
  entity_type: string
  entity_id: number
  is_synced: boolean
  created_at: string
  synced_at: string | null
}

export interface SyncStatusResponse {
  provider: string
  last_sync_at: string | null
  status: string
  pending_count: number
}

export interface CloudSyncResponse {
  pushed?: number | null
  pulled?: number | null
  provider: string
}

// ── Templates ──────────────────────────────────────────────────────────

export interface TemplateResponse {
  id: number
  name: string
  body: string
  is_builtin: boolean
  created_at: string
  updated_at: string
}

export interface TemplateCreate {
  name: string
  body: string
}

export interface TemplateUpdate {
  name?: string | null
  body?: string | null
}
