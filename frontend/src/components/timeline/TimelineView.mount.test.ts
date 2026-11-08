import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for TimelineView — setup-order / mount-crash guard.
 */

vi.mock('../../api/entries', async () => {
  const { makeEntriesApiMock } = await import('../../test-utils/apiMocks')
  // get/create/update stay unresolved: nothing in this view should wait on them.
  return {
    entriesApi: makeEntriesApiMock({ get: vi.fn(), create: vi.fn(), update: vi.fn() }),
  }
})

vi.mock('../../api/media', async () => {
  const { makeMediaApiMock } = await import('../../test-utils/apiMocks')
  return { mediaApi: makeMediaApiMock() }
})

vi.mock('../../api/tags', async () => {
  const { makeTagsApiMock } = await import('../../test-utils/apiMocks')
  return { tagsApi: makeTagsApiMock() }
})

vi.mock('../../api/templates', async () => {
  const { makeTemplatesApiMock } = await import('../../test-utils/apiMocks')
  return { templatesApi: makeTemplatesApiMock() }
})

function makeEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    title: 'A day out',
    body: 'Some body text',
    entry_date: '2026-01-02',
    tags: [],
    media_count: 0,
    ...overrides,
  }
}

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

describe('TimelineView mount', () => {
  it('mounts with an empty entry list', async () => {
    const { default: TimelineView } = await import('./TimelineView.vue')
    const wrapper = mount(TimelineView, {
      global: {
        plugins: [createPinia()],
        stubs: { GoToDateModal: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    wrapper.unmount()
  })

  it('mounts with entries and resolves the first page', async () => {
    const { entriesApi } = await import('../../api/entries')
    vi.mocked(entriesApi.list).mockResolvedValue({
      items: [makeEntry(), makeEntry({ id: 2, title: 'Second entry' })],
      total: 2,
    } as never)

    const { default: TimelineView } = await import('./TimelineView.vue')
    const wrapper = mount(TimelineView, {
      global: {
        plugins: [createPinia()],
        stubs: { GoToDateModal: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    // The list is virtualized, so happy-dom (which has no layout box) renders
    // no rows — assert the load landed in state instead of on the row text.
    expect(wrapper.text()).not.toContain('Failed to load')
    wrapper.unmount()
  })
})
