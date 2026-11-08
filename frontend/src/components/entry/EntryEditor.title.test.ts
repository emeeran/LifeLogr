import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'

/**
 * TITLE-7 — editor save wiring for auto-title (EntryEditor):
 * save with an empty title fills it from the body's first line; a typed
 * title is never overwritten. (The pure derivation rules live in
 * utils/autoTitle.test.ts; the maintenance mirror in the backend suite.)
 */

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
}))

vi.mock('../../api/entries', () => ({
  entriesApi: {
    calendarMonth: vi.fn(async () => []),
    // A minimal well-formed entry: `loadEntry` reads tags/body/mood/template_id
    // off it, and `{}` here used to throw an unhandled rejection after save().
    get: vi.fn(async () => ({
      id: 7,
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
    })),
    list: vi.fn(async () => ({ items: [], total: 0 })),
    create: mocks.create,
    update: mocks.update,
    delete: vi.fn(),
  },
}))

// The editor prewarms TTS after a successful save; without this mock the
// request hits the default origin and pollutes the run with ECONNREFUSED.
vi.mock('../../api/tts', () => ({
  ttsApi: {
    entryAudioUrl: vi.fn(async () => ''),
    speakUrl: vi.fn(async () => ({ key: '' })),
    fileUrl: vi.fn(() => ''),
    prewarmEntry: vi.fn(async () => undefined),
    prewarmText: vi.fn(async () => undefined),
  },
}))

vi.mock('../../api/media', () => ({
  mediaApi: {
    upload: vi.fn(),
    uploadFromPath: vi.fn(),
    extractText: vi.fn(),
    fileUrl: vi.fn(() => ''),
    listByEntry: vi.fn(async () => []),
    listAll: vi.fn(async () => ({ items: [], total: 0 })),
    delete: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../../api/ai', () => ({
  aiStatus: vi.fn(async () => ({ ollama_available: false, model_loaded: false })),
  suggestTags: vi.fn(async () => ({ tags: [] })),
}))

vi.mock('../../api/encryption', () => ({
  encryptText: vi.fn(async () => ({ encrypted: '' })),
  decryptText: vi.fn(async () => ({ decrypted: '' })),
}))

vi.mock('../../api/recordings', () => ({
  recordingsApi: {
    upload: vi.fn(),
    start: vi.fn(async () => undefined),
    stop: vi.fn(async () => ({ id: 1 })),
    listByEntry: vi.fn(async () => []),
    get: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('../../api/templates', () => ({
  templatesApi: {
    list: vi.fn(async () => []),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}))

vi.mock('../../api/tags', () => ({
  tagsApi: {
    list: vi.fn(async () => []),
    tree: vi.fn(async () => []),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.create.mockImplementation(async (payload: Record<string, unknown>) => ({
    id: 7,
    ...payload,
  }))
  mocks.update.mockResolvedValue({ id: 7 })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia
  }
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
})

async function mountNewEditor(): Promise<VueWrapper> {
  const { default: EntryEditor } = await import('./EntryEditor.vue')
  const pinia = createPinia()
  const wrapper = mount(EntryEditor, { global: { plugins: [pinia] } })
  const { useUiStore } = await import('../../stores/ui')
  useUiStore(pinia).requestNewEntry('2026-11-07')
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('EntryEditor auto-title on save (TITLE-7)', () => {
  it('save with an empty title fills it from the body first line', async () => {
    const wrapper = await mountNewEditor()
    const vm = wrapper.vm as unknown as { body: string; save: () => Promise<boolean> }
    // `body` is an exposed ref — the expose proxy unwraps reads AND writes.
    vm.body = '# Ridge walk\n\nNotes about the hike.'

    const saved = await vm.save()
    expect(saved).toBe(true)
    expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(mocks.create.mock.calls[0][0].title).toBe('Ridge walk')

    // The editor's own title buffer carries the derived title (visible in the
    // title input on a real render; happy-dom's re-render of the title chip
    // throws, so only the buffer/payload is asserted here).
    wrapper.unmount()
  })

  it('a typed title is never overwritten by the body', async () => {
    const wrapper = await mountNewEditor()
    const vm = wrapper.vm as unknown as { body: string; save: () => Promise<boolean> }

    const titleInput = wrapper.find('input[placeholder="Title"]')
    await titleInput.setValue('My own title')
    vm.body = '# Heading that must be ignored\n\nBody.'

    await vm.save()
    expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(mocks.create.mock.calls[0][0].title).toBe('My own title')
    wrapper.unmount()
  })
})
