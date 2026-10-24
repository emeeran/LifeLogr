import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for EntryEditor (journal editor).
 *
 * Guards against setup-order crashes that pure-helper unit tests can't see:
 * an eagerly-evaluated `watch(..., { immediate: true })` or a top-level
 * `await`-less promise chain placed above the refs it reads throws during
 * setup, and Vue logs the error but the editor silently never renders. If
 * this mounts, setup ran to completion and the editor DOM is present.
 */

vi.mock('../../api/entries', () => ({
  entriesApi: {
    calendarMonth: vi.fn(async () => []),
    get: vi.fn(async () => ({}) as unknown),
    list: vi.fn(async () => ({ items: [], total: 0 })),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
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
  aiStatus: vi.fn(async () => ({
    ollama_available: false,
    model_loaded: false,
  })),
  suggestTags: vi.fn(async () => ({ tags: [] })),
}))

vi.mock('../../api/encryption', () => ({
  encryptText: vi.fn(async () => ({ encrypted: '' })),
  decryptText: vi.fn(async () => ({ decrypted: '' })),
}))

vi.mock('../../api/recordings', () => ({
  recordingsApi: {
    upload: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
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

// happy-dom lacks a few browser APIs the editor's composables touch.
beforeEach(() => {
  setActivePinia(createPinia())
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

describe('EntryEditor mount', () => {
  it('mounts a new (unsaved) entry without throwing during setup', async () => {
    const { default: EntryEditor } = await import('./EntryEditor.vue')
    const { useUiStore } = await import('../../stores/ui')
    const ui = useUiStore()
    ui.requestNewEntry('2026-10-18')

    const wrapper = mount(EntryEditor, {
      global: {
        plugins: [createPinia()],
        stubs: {
          EncryptionBadge: true,
          EditorToolbar: true,
          EditorStatusBar: true,
          EditorContextMenu: true,
          TagAutocomplete: true,
          MediaViewer: true,
          MediaGrid: true,
          TemplatePicker: true,
          EmojiPicker: true,
          FloatingRecorder: true,
          EntryRecordings: true,
          FloatingPlayback: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    // Setup completed far enough to expose its API and render the editor DOM.
    expect(wrapper.element).toBeTruthy()
    expect((wrapper.vm as { isDirty?: unknown }).isDirty).toBeDefined()
    wrapper.unmount()
  })

  it('mounts while loading an existing entry id', async () => {
    const { default: EntryEditor } = await import('./EntryEditor.vue')
    const { useUiStore } = await import('../../stores/ui')
    const ui = useUiStore()
    ui.startEditing(42)

    const wrapper = mount(EntryEditor, {
      global: {
        plugins: [createPinia()],
        stubs: {
          EncryptionBadge: true,
          EditorToolbar: true,
          EditorStatusBar: true,
          EditorContextMenu: true,
          TagAutocomplete: true,
          MediaViewer: true,
          MediaGrid: true,
          TemplatePicker: true,
          EmojiPicker: true,
          FloatingRecorder: true,
          EntryRecordings: true,
          FloatingPlayback: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    wrapper.unmount()
  })
})
