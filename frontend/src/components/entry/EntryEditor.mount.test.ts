import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
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

vi.mock('../../api/entries', async () => {
  const { makeEntriesApiMock } = await import('../../test-utils/apiMocks')
  return { entriesApi: makeEntriesApiMock() }
})

vi.mock('../../api/tts', async () => {
  const { makeTtsApiMock } = await import('../../test-utils/apiMocks')
  return { ttsApi: makeTtsApiMock() }
})

vi.mock('../../api/media', async () => {
  const { makeMediaApiMock } = await import('../../test-utils/apiMocks')
  return { mediaApi: makeMediaApiMock() }
})

vi.mock('../../api/ai', async () => {
  const { makeAiMocks } = await import('../../test-utils/apiMocks')
  return makeAiMocks()
})

vi.mock('../../api/encryption', async () => {
  const { makeEncryptionMocks } = await import('../../test-utils/apiMocks')
  return makeEncryptionMocks()
})

vi.mock('../../api/recordings', async () => {
  const { makeRecordingsApiMock } = await import('../../test-utils/apiMocks')
  return { recordingsApi: makeRecordingsApiMock() }
})

vi.mock('../../api/templates', async () => {
  const { makeTemplatesApiMock } = await import('../../test-utils/apiMocks')
  return { templatesApi: makeTemplatesApiMock() }
})

vi.mock('../../api/tags', async () => {
  const { makeTagsApiMock } = await import('../../test-utils/apiMocks')
  return { tagsApi: makeTagsApiMock() }
})

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

  // ── MIC-5: mic next to the speaker in the bottom bar ──
  // The FAB was removed (MIC-1): the mic trigger lives in the editor's bottom
  // controls bar, immediately before the read-aloud speaker; the recording
  // pill stays a popover anchored above that band (bottom-20, MIC-2).
  it('mic and speaker are siblings in the toolbar, mic first', async () => {
    const { default: EntryEditor } = await import('./EntryEditor.vue')
    const { useUiStore } = await import('../../stores/ui')
    const pinia = createPinia()
    const wrapper = mount(EntryEditor, { global: { plugins: [pinia] } })
    // Bind the store to the component's pinia explicitly — a store from a
    // different instance silently leaves the mic disabled (hasEntry false).
    const ui = useUiStore(pinia)
    ui.startEditing(42)
    await flushPromises()
    await nextTick()

    const mic = wrapper.find('button[aria-label="Record voice memo"]')
    const speaker = wrapper.find('button[aria-label="Read aloud"]')
    expect(mic.exists()).toBe(true)
    expect(speaker.exists()).toBe(true)
    // Siblings in the same controls bar, mic immediately before the speaker.
    expect(mic.element.parentElement).toBe(speaker.element.parentElement)
    expect(mic.element.nextElementSibling).toBe(speaker.element)
    // With a persisted entry the mic is enabled.
    expect(mic.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('clicking the mic starts a recording; the pill band anchors above', async () => {
    const { default: EntryEditor } = await import('./EntryEditor.vue')
    const { useUiStore } = await import('../../stores/ui')
    const pinia = createPinia()
    const wrapper = mount(EntryEditor, { global: { plugins: [pinia] } })
    const ui = useUiStore(pinia)
    ui.startEditing(42)
    await flushPromises()
    await nextTick()

    // Re-find after the entry fetch settles — the load re-renders the bar and
    // a stale element reference would click a detached node.
    const mic = wrapper.find('button[aria-label="Record voice memo"]')
    expect(mic.attributes('disabled')).toBeUndefined()
    await mic.trigger('click')
    await flushPromises()
    await flushPromises()

    const recordingsApi = (await import('../../api/recordings')).recordingsApi
    expect(vi.mocked(recordingsApi.start).mock.calls.length).toBe(1)

    // The recording pill (FloatingRecorder) mounts in the bottom-20 popover
    // band — happy-dom has no layout, so the "above the button" contract
    // (MIC-2) is the anchor class, not geometry. Its Stop control carries the
    // same "Stop recording" label the toolbar mic switches to while recording
    // (the aria-label ternary on the shared recording ref).
    const pillBand = wrapper.find('.bottom-20')
    expect(pillBand.exists()).toBe(true)
    expect(pillBand.text()).toContain('Stop')
    const stopControl = pillBand.find('button[title="Stop recording"]')
    expect(stopControl.exists()).toBe(true)
    wrapper.unmount()
  })
})
