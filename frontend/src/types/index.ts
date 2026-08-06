export interface TagBrief {
  id: number;
  name: string;
}

export interface TagResponse {
  id: number;
  name: string;
  parent_id: number | null;
  children: TagBrief[];
  entry_count: number;
}

export interface TagCreate {
  name: string;
  parent_id?: number | null;
}

export interface TagUpdate {
  name: string;
}

export interface EntryResponse {
  id: number;
  entry_date: string;
  title: string | null;
  body: string;
  summary: string | null;
  is_deleted: boolean;
  is_encrypted: boolean;
  tags: TagBrief[];
  media_count: number;
  has_recording: boolean;
  created_at: string;
  updated_at: string;
  template_id: number | null;
}

/** Lightweight entry projection for calendar grid (excludes body/media). */
export interface CalendarEntryResponse {
  id: number;
  entry_date: string;
  title: string | null;
  mood: string | null;
  is_encrypted: boolean;
  tags: TagBrief[];
}

/** Lightweight entry for list/timeline views: full ``body`` replaced by a
 *  server-side snippet so list queries don't load every entry's full body. */
export interface EntryListItem extends Omit<EntryResponse, 'body'> {
  body_snippet: string;
}

export interface EntryListResponse {
  items: EntryListItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface EntryCreate {
  entry_date: string;
  title?: string | null;
  body: string;
  tag_ids?: number[];
  template_id?: number | null;
}

export interface EntryUpdate {
  title?: string | null;
  body?: string | null;
  tag_ids?: number[] | null;
}

// ── Notes ──────────────────────────────────────────────────────────────

export interface NoteFolderResponse {
  id: number;
  name: string;
  parent_id: number | null;
  color: string | null;
  sort_order: number;
  note_count: number;
  created_at: string;
  updated_at: string;
}

export interface NoteFolderCreate {
  name: string;
  parent_id?: number | null;
  color?: string | null;
  sort_order?: number;
}

export interface NoteFolderUpdate {
  name?: string;
  color?: string | null;
  sort_order?: number;
  parent_id?: number | null;
  clear_parent?: boolean;
}

export interface NotePageResponse {
  id: number;
  note_id: number;
  title: string | null;
  body: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface NotePageCreate {
  title?: string | null;
  body?: string;
}

export interface NotePageUpdate {
  title?: string | null;
  body?: string;
  sort_order?: number;
}

export interface NotePageReorderItem {
  id: number;
  sort_order: number;
}

export interface NoteResponse {
  id: number;
  folder_id: number | null;
  title: string | null;
  body: string;
  is_pinned: boolean;
  color: string | null;
  is_encrypted: boolean;
  encrypted_at: string | null;
  tags: TagBrief[];
  pages: NotePageResponse[];
  created_at: string;
  updated_at: string;
}

export interface NoteCreate {
  title?: string | null;
  body?: string;
  folder_id?: number | null;
  tag_ids?: number[];
  color?: string | null;
  is_pinned?: boolean;
}

export interface NoteUpdate {
  title?: string | null;
  body?: string | null;
  folder_id?: number | null;
  clear_folder?: boolean;
  tag_ids?: number[] | null;
  is_pinned?: boolean | null;
  color?: string | null;
}

/** Lightweight note for list views: full ``body`` + nested ``pages`` replaced by
 *  a server-side snippet so list queries don't load bodies. */
export interface NoteListItem extends Omit<NoteResponse, 'body' | 'pages'> {
  body_snippet: string;
}

export interface NoteListResponse {
  items: NoteListItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface NoteListParams extends PaginatedParams {
  folder_id?: number | null;
  tag_ids?: number[];
  is_pinned?: boolean;
}

export interface NoteEncryptionStatusResponse {
  note_id: number;
  is_encrypted: boolean;
  encrypted_at: string | null;
}

export interface NoteMediaResponse {
  id: number;
  note_id: number;
  filename: string;
  media_type: string;
  file_size: number;
  caption: string | null;
  created_at: string;
}

export interface MediaResponse {
  id: number;
  entry_id: number;
  filename: string;
  media_type: string;
  file_size: number;
  caption: string | null;
  created_at: string;
}

export interface MediaTimelineItem extends MediaResponse {
  entry_date: string;
  entry_title: string | null;
}

export interface MediaTimelineResponse {
  items: MediaTimelineItem[];
  total: number;
}

export interface VoiceRecordingResponse {
  id: number;
  entry_id: number;
  media_id: number;
  duration_seconds: number;
  audio_format: string;
  created_at: string;
}

export interface BackupConfigCreate {
  provider: string;
  label?: string | null;
  credentials: Record<string, string>;
  schedule_cron?: string | null;
}

export interface BackupConfigResponse {
  id: number;
  provider: string;
  label: string | null;
  schedule_cron: string | null;
  last_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackupSnapshotResponse {
  id: number;
  config_id: number;
  status: string;
  entries_synced: number;
  media_synced: number;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  backup_filename: string | null;
}

export interface PaginatedParams {
  offset?: number;
  limit?: number;
}

export interface EntryListParams extends PaginatedParams {
  tag_ids?: number[];
  year?: number;
  month?: number;
  template_id?: number;
}

// ── AI (Ollama) ──────────────────────────────────────────────────────

export interface GrammarSuggestion {
  offset: number;
  length: number;
  original: string;
  suggestion: string;
  rule_id: string;
  message: string;
}

export interface GrammarCheckResponse {
  corrected_text: string;
  suggestions: GrammarSuggestion[];
}

export interface SpellCheckResponse {
  corrected_text: string;
  misspellings: GrammarSuggestion[];
}

export interface RewriteResponse {
  rewritten_text: string;
  style: string;
}

export interface AIStatusResponse {
  ollama_available: boolean;
  model_name: string;
  model_loaded: boolean;
  embed_model_available: boolean;
  error: string | null;
}

// ── AI Tag Suggestions ──────────────────────────────────────────────

export interface TagSuggestionResponse {
  tags: string[];
}

// ── AI Writer's Block ───────────────────────────────────────────────

export interface ContinueWritingResponse {
  continuation: string;
}

// ── AI Smart Tools ──────────────────────────────────────────────────

export interface ExpandResponse {
  expanded_text: string;
}

export interface ChangeToneResponse {
  changed_text: string;
  tone: string;
}

// ── AI Analyze Text ──────────────────────────────────────────────────

export interface AnalyzeTextResponse {
  emotions: string[];
  themes: string[];
  summary: string;
}

// ── AI Define Text ───────────────────────────────────────────────────

export interface DefineTextResponse {
  definition: string;
}

export interface VoiceChangeResponse {
  changed_text: string;
  voice: string;
}

export interface RewriteForClarityResponse {
  rewritten_text: string;
}

// ── AI Themes ───────────────────────────────────────────────────────

export interface ThemeInsight {
  theme: string;
  frequency: string;
  months_mentioned: string[];
  insight: string;
}

export interface ThemesResponse {
  themes: ThemeInsight[];
}

// ── Encryption ───────────────────────────────────────────────────────

export interface EncryptionStatusResponse {
  entry_id: number;
  is_encrypted: boolean;
  encrypted_at: string | null;
}

// ── Video Notes ──────────────────────────────────────────────────────

export interface VideoNoteResponse {
  id: number;
  entry_id: number;
  filename: string;
  duration_seconds: number | null;
  thumbnail_path: string | null;
  created_at: string;
}

// ── Search (FTS5) ────────────────────────────────────────────────────

export interface SearchResultEntry {
  id: number;
  type: "entry" | "note" | "reminder";
  entry_date: string | null;
  folder_id?: number | null;
  updated_at?: string | null;
  title: string | null;
  snippet: string;
  rank: number;
  similarity_score?: number | null;
}

export interface GlobalSearchResponse {
  items: SearchResultEntry[];
  total: number;
  offset: number;
  limit: number;
}

// ── Analytics ─────────────────────────────────────────────────────────

export interface OverviewResponse {
  total_entries: number;
  total_words: number;
  total_media: number;
  total_recordings: number;
  date_range_start: string | null;
  date_range_end: string | null;
  longest_streak: number;
  current_streak: number;
}

export interface WritingHabitResponse {
  day_of_week: number;
  day_name: string;
  entry_count: number;
}

export interface WordCountResponse {
  total_words: number;
  average_words_per_entry: number;
  longest_entry_words: number;
  shortest_entry_words: number;
}

export interface TagStatsResponse {
  tag_id: number;
  tag_name: string;
  usage_count: number;
}

export interface HeatmapDayResponse {
  date: string;
  count: number;
}

export interface HeatmapResponse {
  year: number;
  days: HeatmapDayResponse[];
}

export interface MediaStatsResponse {
  total_images: number;
  total_videos: number;
  total_recordings: number;
  total_size_bytes: number;
}

// ── Reminders ────────────────────────────────────────────────────────

export interface ReminderResponse {
  id: number;
  title: string;
  message: string | null;
  reminder_time: string;
  days_of_week: string;
  is_active: boolean;
  last_fired_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReminderCreate {
  title: string;
  message?: string | null;
  reminder_time: string;
  days_of_week?: string;
  is_active?: boolean;
}

export interface ReminderUpdate {
  title?: string | null;
  message?: string | null;
  reminder_time?: string | null;
  days_of_week?: string | null;
  is_active?: boolean | null;
}

// ── Templates ──────────────────────────────────────────────────────────

export interface TemplateResponse {
  id: number;
  name: string;
  body: string;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface TemplateCreate {
  name: string;
  body: string;
}

export interface TemplateUpdate {
  name?: string | null;
  body?: string | null;
}
