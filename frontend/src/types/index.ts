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

export interface EntryListResponse {
  items: EntryResponse[];
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

export interface NoteListResponse {
  items: NoteResponse[];
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
  type: "entry" | "note" | "task" | "reminder";
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

// ── Contacts ─────────────────────────────────────────────────────────

export interface ContactTypedValue {
  type: string;
  value: string;
}

export interface ContactAddress {
  type: string;
  street?: string | null;
  city?: string | null;
  region?: string | null;
  postal_code?: string | null;
  country?: string | null;
}

export interface ContactDateValue {
  type: string;
  label?: string | null;
  date: string;
}

export interface ContactGroupBrief {
  id: number;
  name: string;
  color: string | null;
}

export interface ContactGroupResponse extends ContactGroupBrief {
  sort_order: number;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContactGroupCreate {
  name: string;
  color?: string | null;
  sort_order?: number;
}

export interface ContactGroupUpdate {
  name?: string;
  color?: string | null;
  sort_order?: number;
}

export interface RelatedEmailResponse {
  id: number;
  account_id: number;
  subject: string | null;
  from_address: string;
  from_name: string | null;
  sent_at: string | null;
  is_read: boolean;
}

export interface ContactResponse {
  id: number;
  name: string | null;
  email: string;
  emails_extra: string[] | null;
  phone: string | null;
  phone_secondary: string | null;
  phones: ContactTypedValue[] | null;
  company: string | null;
  title: string | null;
  department: string | null;
  profession: string | null;
  nickname: string | null;
  addresses: ContactAddress[] | null;
  im_handles: ContactTypedValue[] | null;
  websites: string[] | null;
  dates: ContactDateValue[] | null;
  relationships: ContactTypedValue[] | null;
  notes: string | null;
  is_favorite: boolean;
  groups: ContactGroupBrief[];
  source: string;
  last_seen_at: string | null;
  email_account_id: number | null;
  photo_path: string | null;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContactCreate {
  name?: string | null;
  email: string;
  emails_extra?: string[] | null;
  phone?: string | null;
  phone_secondary?: string | null;
  phones?: ContactTypedValue[] | null;
  company?: string | null;
  title?: string | null;
  department?: string | null;
  profession?: string | null;
  nickname?: string | null;
  addresses?: ContactAddress[] | null;
  im_handles?: ContactTypedValue[] | null;
  websites?: string[] | null;
  dates?: ContactDateValue[] | null;
  relationships?: ContactTypedValue[] | null;
  notes?: string | null;
  is_favorite?: boolean;
  group_ids?: number[] | null;
}

export interface ContactUpdate {
  name?: string | null;
  email?: string | null;
  emails_extra?: string[] | null;
  phone?: string | null;
  phone_secondary?: string | null;
  phones?: ContactTypedValue[] | null;
  company?: string | null;
  title?: string | null;
  department?: string | null;
  profession?: string | null;
  nickname?: string | null;
  addresses?: ContactAddress[] | null;
  im_handles?: ContactTypedValue[] | null;
  websites?: string[] | null;
  dates?: ContactDateValue[] | null;
  relationships?: ContactTypedValue[] | null;
  notes?: string | null;
  is_favorite?: boolean | null;
  group_ids?: number[] | null;
}

export interface ContactListResponse {
  items: ContactResponse[];
  total: number;
  offset: number;
  limit: number;
}

// ── Planner: Tasks & Schedule ─────────────────────────────────────────

export type TaskPriority = "low" | "medium" | "high";

export interface TaskListResponse {
  id: number;
  name: string;
  color: string | null;
  sort_order: number;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskListCreate {
  name: string;
  color?: string | null;
  sort_order?: number;
}

export interface TaskResponse {
  id: number;
  parent_id: number | null;
  list_id: number | null;
  title: string;
  notes: string | null;
  is_completed: boolean;
  completed_at: string | null;
  priority: TaskPriority | null;
  due_date: string | null;
  sort_order: number;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
  subtasks: TaskResponse[];
}

export interface TaskCreate {
  title: string;
  list_id?: number | null;
  parent_id?: number | null;
  notes?: string | null;
  priority?: TaskPriority | null;
  due_date?: string | null;
  sort_order?: number;
}

export interface TaskUpdate {
  title?: string;
  list_id?: number | null;
  parent_id?: number | null;
  notes?: string | null;
  priority?: TaskPriority | null;
  due_date?: string | null;
  sort_order?: number;
}

export interface ScheduleEventResponse {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  rrule: string | null;
  timezone_name: string | null;
  color: string | null;
  excluded_dates: string[] | null;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScheduleEventCreate {
  title: string;
  description?: string | null;
  location?: string | null;
  start_at: string;
  end_at: string;
  all_day?: boolean;
  rrule?: string | null;
  timezone_name?: string | null;
  color?: string | null;
}

export interface ScheduleEventUpdate extends Partial<ScheduleEventCreate> {}

export interface AgendaItem {
  event_id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  color: string | null;
  is_recurring: boolean;
}

export interface AgendaResponse {
  items: AgendaItem[];
  total: number;
  frm: string;
  to: string;
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

// ── Sync ─────────────────────────────────────────────────────────────

export interface SyncQueueItem {
  id: number;
  operation: string;
  entity_type: string;
  entity_id: number;
  is_synced: boolean;
  created_at: string;
  synced_at: string | null;
}

export interface SyncStatusResponse {
  provider: string;
  last_sync_at: string | null;
  status: string;
  pending_count: number;
}

export interface CloudSyncResponse {
  pushed?: number | null;
  pulled?: number | null;
  provider: string;
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

// ── Email ───────────────────────────────────────────────────────────────

export interface EmailAddress {
  address: string;
  name: string | null;
}

export interface EmailAccountResponse {
  id: number;
  label: string;
  email_address: string;
  imap_host: string;
  imap_port: number;
  imap_use_ssl: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  username: string;
  display_name: string | null;
  sync_enabled: boolean;
  poll_interval_minutes: number;
  last_synced_at: string | null;
  last_sync_error: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmailAccountCreate {
  label: string;
  email_address: string;
  imap_host: string;
  imap_port?: number;
  imap_use_ssl?: boolean;
  smtp_host: string;
  smtp_port?: number;
  smtp_use_tls?: boolean;
  username: string;
  password: string;
  display_name?: string | null;
  poll_interval_minutes?: number;
}

export interface EmailAccountUpdate {
  label?: string;
  email_address?: string;
  imap_host?: string;
  imap_port?: number | null;
  imap_use_ssl?: boolean | null;
  smtp_host?: string;
  smtp_port?: number | null;
  smtp_use_tls?: boolean | null;
  username?: string;
  password?: string | null;
  display_name?: string | null;
  sync_enabled?: boolean | null;
  poll_interval_minutes?: number | null;
  is_active?: boolean | null;
}

export interface EmailAccountTestResult {
  success: boolean;
  error: string | null;
}

export interface EmailFolderResponse {
  id: number;
  account_id: number;
  folder_name: string;
  display_name: string | null;
  special_use: string | null;
  message_count: number;
  unread_count: number;
  sync_enabled: boolean;
}

export interface EmailAttachmentResponse {
  id: number;
  message_id: number;
  filename: string;
  content_type: string;
  file_size: number;
  content_id: string | null;
  is_inline: boolean;
}

export interface EmailMessageListResponse {
  id: number;
  account_id: number;
  folder_id: number;
  from_address: string;
  from_name: string | null;
  to_addresses: EmailAddress[];
  subject: string | null;
  snippet: string | null;
  sent_at: string | null;
  is_read: boolean;
  is_starred: boolean;
  has_attachments: boolean;
  is_spam: boolean;
  spam_score: number | null;
}

export interface EmailMessageResponse extends EmailMessageListResponse {
  cc_addresses: EmailAddress[] | null;
  bcc_addresses: EmailAddress[] | null;
  reply_to: string | null;
  text_body: string | null;
  html_body: string | null;
  in_reply_to: string | null;
  is_draft: boolean;
  attachments: EmailAttachmentResponse[];
}

export interface EmailMessageListResult {
  items: EmailMessageListResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface EmailListParams {
  account_id?: number;
  folder_id?: number;
  unread_only?: boolean;
  starred_only?: boolean;
  search?: string;
  exclude_spam?: boolean;
  spam_only?: boolean;
  offset?: number;
  limit?: number;
}

export interface SpamRuleResponse {
  id: number;
  pattern: string;
  is_domain: boolean;
  /** "junk" → segregate as spam; "delete" → drop existing + future mail. */
  action: string;
  created_at: string;
}

export interface SpamRuleCreate {
  pattern: string;
  is_domain?: boolean;
  action?: 'junk' | 'delete';
}

/** Result of blocking a message's sender (applies to existing + future mail). */
export interface BlockSenderResult {
  rule: SpamRuleResponse;
  action: 'junk' | 'delete';
  affected: number;
}

export interface EmailCompose {
  account_id: number;
  to: string[];
  cc?: string[] | null;
  bcc?: string | null;
  subject: string;
  text_body?: string;
  html_body?: string | null;
  in_reply_to_message_id?: number | null;
  attachment_ids?: string[];
}

export interface EmailSendResult {
  success: boolean;
  sent_message_id: number | null;
  error: string | null;
}

export interface TempAttachmentResponse {
  id: string;
  filename: string;
  file_size: number;
}
