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

vi.mock('../../api/entries', async () => {
  const { makeEntriesApiMock } = await import('../../test-utils/apiMocks')
  return { entriesApi: makeEntriesApiMock({ create: mocks.create, update: mocks.update }) }
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
