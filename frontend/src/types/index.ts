export interface TagBrief {
  id: number
  name: string
  /** Tracker tag (Diarium Type=2 import). */
  is_tracker?: boolean
  /** Per-entry reading, only populated on entry-detail responses. */
  tracking_value?: string | null
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

/** A per-entry event (weather from Diarium imports; unknown vendor types
 *  are carried verbatim as kind "unknown:<n>"). */
export interface EntryEventBrief {
  id: number
  kind: string
  content: string
  label: string | null
}

export interface EntryResponse {
  id: number
  entry_date: string
  title: string | null
  body: string
  summary: string | null
  mood?: string | null
  is_deleted: boolean
  is_encrypted: boolean
  tags: TagBrief[]
  events: EntryEventBrief[]
  media_count: number
  has_recording: boolean
  created_at: string
  updated_at: string
  template_id: number | null
}

/** Lightweight entry projection for calendar grid (excludes body/media). */
export interface CalendarEntryResponse {
  id: number
  entry_date: string
  title: string | null
  mood: string | null
  is_encrypted: boolean
  /** Server-side word count of the body (0 for encrypted entries). */
  word_count: number
  tags: TagBrief[]
}

export interface WeeklyCount {
  /** ISO date (YYYY-MM-DD) of the week's Monday. */
  week_start: string
  count: number
}

export interface JournalStats {
  total_entries: number
  total_words: number
  current_streak: number
  longest_streak: number
  weekly: WeeklyCount[]
  moods: { mood: string; count: number }[]
  media: { media_type: string; count: number }[]
}

/** Lightweight entry for list/timeline views: full ``body`` replaced by a
 *  server-side snippet so list queries don't load every entry's full body. */
export interface EntryListItem extends Omit<EntryResponse, 'body'> {
  body_snippet: string
}

export interface EntryListResponse {
  items: EntryListItem[]
  total: number
  offset: number
  limit: number
}

export interface EntryCreate {
  entry_date: string
  title?: string | null
  body: string
  tag_ids?: number[]
  template_id?: number | null
  mood?: string | null
}

export interface EntryUpdate {
  title?: string | null
  body?: string | null
  tag_ids?: number[] | null
  mood?: string | null
}

// ── Notes ──────────────────────────────────────────────────────────────

export interface NoteFolderResponse {
  id: number
  name: string
  parent_id: number | null
  color: string | null
  sort_order: number
  note_count: number
  created_at: string
  updated_at: string
}

export interface NoteFolderCreate {
  name: string
  parent_id?: number | null
  color?: string | null
  sort_order?: number
}

export interface NoteFolderUpdate {
  name?: string
  color?: string | null
  sort_order?: number
  parent_id?: number | null
  clear_parent?: boolean
}

export interface NotePageResponse {
  id: number
  note_id: number
  title: string | null
  body: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface NotePageCreate {
  title?: string | null
  body?: string
}

export interface NotePageUpdate {
  title?: string | null
  body?: string
  sort_order?: number
}

export interface NotePageReorderItem {
  id: number
  sort_order: number
}

/** One entry of a rail reorder batch (DND-3) — notes or notebooks. */
export interface ReorderItem {
  id: number
  sort_order: number
}

export interface NoteResponse {
  id: number
  folder_id: number | null
  title: string | null
  body: string
  is_pinned: boolean
  color: string | null
  is_encrypted: boolean
  encrypted_at: string | null
  tags: TagBrief[]
  pages: NotePageResponse[]
  /** Manual drag order within a section (DND-3); 0 = never moved (recent-first). */
  sort_order: number
  created_at: string
  updated_at: string
}

export interface NoteCreate {
  title?: string | null
  body?: string
  folder_id?: number | null
  color?: string | null
  is_pinned?: boolean
}

export interface NoteUpdate {
  title?: string | null
  body?: string | null
  folder_id?: number | null
  clear_folder?: boolean
  is_pinned?: boolean | null
  color?: string | null
}

/** Lightweight note for list views: full ``body`` + nested ``pages`` replaced by
 *  a server-side snippet so list queries don't load bodies. */
export interface NoteListItem extends Omit<NoteResponse, 'body' | 'pages'> {
  body_snippet: string
}

export interface NoteListResponse {
  items: NoteListItem[]
  total: number
  offset: number
  limit: number
}

export interface NoteListParams extends PaginatedParams {
  folder_id?: number | null
  tag_ids?: number[]
  is_pinned?: boolean
}

export interface NoteEncryptionStatusResponse {
  note_id: number
  is_encrypted: boolean
  encrypted_at: string | null
}

export interface NoteMediaResponse {
  id: number
  note_id: number
  filename: string
  media_type: string
  file_size: number
  caption: string | null
  created_at: string
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
  created_at: string
}

export interface BackupConfigCreate {
  provider: string
  label?: string | null
  credentials: Record<string, string>
  schedule_cron?: string | null
}

export interface BackupConfigResponse {
  id: number
  provider: string
  label: string | null
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
  backup_filename: string | null
}

export interface PaginatedParams {
  offset?: number
  limit?: number
}

export interface EntryListParams extends PaginatedParams {
  tag_ids?: number[]
  year?: number
  month?: number
  template_id?: number
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

// ── AI Smart Tools ──────────────────────────────────────────────────

export interface ExpandResponse {
  expanded_text: string
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

// ── Search (FTS5) ────────────────────────────────────────────────────

export interface SearchResultEntry {
  id: number
  type: 'entry' | 'note' | 'reminder'
  entry_date: string | null
  folder_id?: number | null
  updated_at?: string | null
  title: string | null
  snippet: string
  rank: number
  similarity_score?: number | null
}

export interface GlobalSearchResponse {
  items: SearchResultEntry[]
  total: number
  offset: number
  limit: number
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
