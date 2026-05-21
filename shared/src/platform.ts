/**
 * PlatformProvider — abstracts data access for desktop (HTTP) vs mobile (direct SQLite).
 *
 * Each sub-api mirrors the shape of the existing frontend/src/api/*.ts modules
 * so stores can be switched over with minimal changes.
 */
import type {
  EntryResponse, EntryListResponse, EntryCreate, EntryUpdate, EntryListParams,
  TagResponse, TagCreate, TagUpdate,
  TemplateResponse, TemplateCreate, TemplateUpdate,
  MediaResponse,
  VoiceRecordingResponse,
  GlobalSearchResponse,
  GrammarCheckResponse, SpellCheckResponse, RewriteResponse, AIStatusResponse,
  RevisionResponse, RevisionDiffResponse,
  GeotagResponse, GeotagUpdate, NearbyEntry,
  ReminderResponse, ReminderCreate, ReminderUpdate,
  OverviewResponse, WritingHabitResponse, WordCountResponse,
  TagStatsResponse, HeatmapResponse, MediaStatsResponse,
} from '../../frontend/src/types'

// ── Sub-API interfaces ────────────────────────────────────────────────

export interface EntryApi {
  create(data: EntryCreate): Promise<EntryResponse>
  get(id: number): Promise<EntryResponse>
  list(params?: EntryListParams): Promise<EntryListResponse>
  update(id: number, data: EntryUpdate): Promise<EntryResponse>
  delete(id: number): Promise<void>
  importEntries(entries: { entry_date: string; title?: string; body: string }[]): Promise<{ imported: number; skipped: number }>
  importFile(file: File): Promise<{ imported: number; skipped: number }>
  resetDatabase(): Promise<{ status: string; message: string }>
  deduplicate(): Promise<{ groups_found: number; duplicates_removed: number }>
  calendarMonth(year: number, month: number): Promise<EntryResponse[]>
  search(query: string, offset?: number, limit?: number): Promise<EntryListResponse>
  exportMarkdownUrl(startDate?: string, endDate?: string): string
}

export interface TagApi {
  create(data: TagCreate): Promise<TagResponse>
  list(): Promise<TagResponse[]>
  tree(): Promise<TagResponse[]>
  update(id: number, data: TagUpdate): Promise<TagResponse>
  delete(id: number): Promise<void>
}

export interface TemplateApi {
  list(): Promise<TemplateResponse[]>
  create(data: TemplateCreate): Promise<TemplateResponse>
  update(id: number, data: TemplateUpdate): Promise<TemplateResponse>
  remove(id: number): Promise<void>
}

export interface MediaApi {
  upload(entryId: number, file: File, caption?: string): Promise<MediaResponse>
  get(id: number): Promise<MediaResponse>
  fileUrl(id: number): string
  delete(id: number): Promise<void>
  listByEntry(entryId: number): Promise<MediaResponse[]>
}

export interface RecordingApi {
  upload(entryId: number, file: File): Promise<VoiceRecordingResponse>
  listByEntry(entryId: number): Promise<VoiceRecordingResponse[]>
  transcribe(id: number): Promise<VoiceRecordingResponse>
  get(id: number): Promise<VoiceRecordingResponse>
  delete(id: number): Promise<void>
}

export interface SearchApi {
  global(query: string, params?: {
    tag_ids?: string; date_from?: string; date_to?: string
    offset?: number; limit?: number
  }): Promise<GlobalSearchResponse>
}

export interface AiApi {
  grammarCheck(text: string): Promise<GrammarCheckResponse>
  spellCheck(text: string): Promise<SpellCheckResponse>
  rewrite(text: string, style?: string, instructions?: string): Promise<RewriteResponse>
  status(): Promise<AIStatusResponse>
}

export interface TtsApi {
  getVoice(): string
  entryUrl(entryId: number): string
  speakBlob(text: string): Promise<Blob>
}

export interface RevisionApi {
  list(entryId: number, offset?: number, limit?: number): Promise<{
    items: RevisionResponse[]; total: number; offset: number; limit: number
  }>
  get(entryId: number, revisionNumber: number): Promise<RevisionResponse>
  diff(entryId: number, fromRev: number, toRev: number): Promise<RevisionDiffResponse>
  restore(entryId: number, revisionNumber: number): Promise<RevisionResponse>
}

export interface GeotagApi {
  set(entryId: number, data: GeotagUpdate): Promise<GeotagResponse>
  remove(entryId: number): Promise<void>
  mapView(): Promise<GeotagResponse[]>
  nearby(lat: number, lon: number, radiusKm?: number, limit?: number): Promise<{
    items: NearbyEntry[]; total: number
  }>
}

export interface ReminderApi {
  create(data: ReminderCreate): Promise<ReminderResponse>
  list(): Promise<ReminderResponse[]>
  update(id: number, data: ReminderUpdate): Promise<ReminderResponse>
  delete(id: number): Promise<void>
  testNotification(id: number): Promise<{ sent: boolean; title: string }>
}

export interface AnalyticsApi {
  overview(): Promise<OverviewResponse>
  habits(): Promise<WritingHabitResponse[]>
  words(): Promise<WordCountResponse>
  tagStats(): Promise<TagStatsResponse[]>
  heatmap(year?: number): Promise<HeatmapResponse>
  mediaStats(): Promise<MediaStatsResponse>
}

export interface ExportApi {
  html(startDate?: string, endDate?: string): Promise<string>
  pdfUrl(startDate?: string, endDate?: string): string
}

// ── Top-level provider ────────────────────────────────────────────────

export interface PlatformProvider {
  entries: EntryApi
  tags: TagApi
  templates: TemplateApi
  media: MediaApi
  recordings: RecordingApi
  search: SearchApi
  ai: AiApi
  tts: TtsApi
  revisions: RevisionApi
  geotag: GeotagApi
  reminders: ReminderApi
  analytics: AnalyticsApi
  export: ExportApi
}
