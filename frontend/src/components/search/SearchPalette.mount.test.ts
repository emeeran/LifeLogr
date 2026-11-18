import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import router from '../../router'

/**
 * Mount smoke test for SearchPalette — setup-order / mount-crash guard.
 *
 * SearchPalette calls `useRouter()` during setup, so the real router from
 * `src/router.ts` is installed as a plugin (a stubbed `$router` would not
 * exercise the real route table the palette pushes to).
 */

vi.mock('../../api/search', () => ({
  globalSearch: vi.fn(async () => ({ items: [], total: 0 })),
}))

vi.mock('../../api/notes', () => ({
  notesApi: {
    list: vi.fn(async () => ({ items: [], total: 0 })),
    listFolders: vi.fn(async () => []),
    get: vi.fn(),
    search: vi.fn(async () => ({ items: [], total: 0 })),
    mediaFileUrl: vi.fn(() => ''),
    uploadMedia: vi.fn(),
    uploadMediaFromPath: vi.fn(),
    exportPageMarkdown: vi.fn(),
  },
}))

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

describe('SearchPalette mount', () => {
  it('mounts the dialog and renders the search input', async () => {
    const { default: SearchPalette } = await import('./SearchPalette.vue')
    const wrapper = mount(SearchPalette, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    expect(wrapper.find('input').exists()).toBe(true)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('runs a debounced query end-to-end and renders the results', async () => {
    const { globalSearch } = await import('../../api/search')
    vi.mocked(globalSearch).mockResolvedValue({
      items: [
        {
          id: 3,
          type: 'entry',
          title: 'Beach day',
          snippet: 'a <mark>beach</mark> day',
          entry_date: '2026-01-02',
          updated_at: '2026-01-02T00:00:00',
          rank: 1,
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    })

    const { default: SearchPalette } = await import('./SearchPalette.vue')
    const wrapper = mount(SearchPalette, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    await wrapper.find('input').setValue('beach')
    // The palette debounces 200ms before firing the search.
    await new Promise((r) => setTimeout(r, 260))
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('Beach day')
    wrapper.unmount()
  })

  it('mounts with search history present', async () => {
    const { useSearchStore } = await import('../../stores/search')
    useSearchStore().searchHistory.push('beach')

    const { default: SearchPalette } = await import('./SearchPalette.vue')
    const wrapper = mount(SearchPalette, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('Recent Searches')
    wrapper.unmount()
  })
})
