import { vi } from 'vitest'

/**
 * Shared vi.mock factories for API modules, so component tests can't drift
 * into returning malformed payloads (a bare `{}` entry mock once made
 * loadEntry throw an unhandled rejection in every editor test run).
 *
 * Usage — vi.mock factories are hoisted, so import the helper inside the
 * factory rather than at the top of the test file:
 *
 *   vi.mock('../../api/media', async () => {
 *     const { makeMediaApiMock } = await import('../../test-utils/apiMocks')
 *     return { mediaApi: makeMediaApiMock() }
 *   })
 */

/** Minimal well-formed EntryResponse. `loadEntry` reads tags/body/mood/
 *  template_id off it; overrides let a test point at specific field values. */
export function makeEntryMock(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    entry_date: '2026-11-07',
    title: null,
    body: '',
    summary: null,
    mood: '',
    is_deleted: false,
    is_encrypted: false,
    tags: [],
    events: [],
    media_count: 0,
    has_recording: false,
    created_at: '',
    updated_at: '',
    template_id: null,
    ...overrides,
  }
}

export function makeEntriesApiMock(overrides: Record<string, unknown> = {}) {
  return {
    calendarMonth: vi.fn(async () => []),
    get: vi.fn(async () => makeEntryMock()),
    list: vi.fn(async () => ({ items: [], total: 0 })),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    ...overrides,
  }
}

export function makeMediaApiMock(overrides: Record<string, unknown> = {}) {
  return {
    upload: vi.fn(),
    uploadFromPath: vi.fn(),
    extractText: vi.fn(),
    fileUrl: vi.fn(() => ''),
    thumbUrl: vi.fn(() => ''),
    listByEntry: vi.fn(async () => []),
    listAll: vi.fn(async () => ({ items: [], total: 0 })),
    get: vi.fn(),
    delete: vi.fn(async () => undefined),
    ...overrides,
  }
}

export function makeTagsApiMock(overrides: Record<string, unknown> = {}) {
  return {
    list: vi.fn(async () => []),
    tree: vi.fn(async () => []),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    ...overrides,
  }
}

export function makeTemplatesApiMock(overrides: Record<string, unknown> = {}) {
  return {
    list: vi.fn(async () => []),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    ...overrides,
  }
}

export function makeRecordingsApiMock(overrides: Record<string, unknown> = {}) {
  return {
    upload: vi.fn(),
    start: vi.fn(async () => undefined),
    // stop() must resolve to a recording: the composable's unmount guard
    // calls `.catch` on the result while a recording is active.
    stop: vi.fn(async () => ({ id: 1 })),
    listByEntry: vi.fn(async () => []),
    get: vi.fn(),
    delete: vi.fn(),
    ...overrides,
  }
}

export function makeEncryptionMocks(overrides: Record<string, unknown> = {}) {
  return {
    encryptText: vi.fn(async () => ({ encrypted: '' })),
    decryptText: vi.fn(async () => ({ decrypted: '' })),
    ...overrides,
  }
}

/** Named api/ai exports used by the editor tests. NoteEditor mocks the
 *  `aiApi` object shape instead — that one stays file-local on purpose. */
export function makeAiMocks(overrides: Record<string, unknown> = {}) {
  return {
    aiStatus: vi.fn(async () => ({
      ollama_available: false,
      model_loaded: false,
    })),
    suggestTags: vi.fn(async () => ({ tags: [] })),
    ...overrides,
  }
}

/** The editor prewarms TTS after a successful save; without this mock the
 *  request hits the default origin and pollutes the run with ECONNREFUSED. */
export function makeTtsApiMock(overrides: Record<string, unknown> = {}) {
  return {
    entryAudioUrl: vi.fn(async () => ''),
    speakUrl: vi.fn(async () => ({ key: '' })),
    fileUrl: vi.fn(() => ''),
    prewarmEntry: vi.fn(async () => undefined),
    prewarmText: vi.fn(async () => undefined),
    ...overrides,
  }
}
