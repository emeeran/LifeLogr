import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for MediaTimelineView — setup-order / mount-crash guard.
 */

vi.mock('../../api/media', () => ({
  mediaApi: {
    listAll: vi.fn(async () => ({ items: [], total: 0 })),
    listByEntry: vi.fn(async () => []),
    fileUrl: vi.fn(() => ''),
    upload: vi.fn(),
    uploadFromPath: vi.fn(),
    extractText: vi.fn(),
    delete: vi.fn(async () => undefined),
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
  window.confirm = vi.fn(() => true)
})

describe('MediaTimelineView mount', () => {
  it('mounts with no media and shows the empty state', async () => {
    const { default: MediaTimelineView } = await import(
      './MediaTimelineView.vue'
    )
    const wrapper = mount(MediaTimelineView, {
      global: {
        plugins: [createPinia()],
        stubs: { MediaViewer: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    expect(wrapper.text()).toContain('All')
    wrapper.unmount()
  })

  it('mounts with media grouped by entry date', async () => {
    const { mediaApi } = await import('../../api/media')
    vi.mocked(mediaApi.listAll).mockResolvedValue({
      items: [
        {
          id: 5,
          entry_id: 11,
          entry_date: '2026-01-02',
          entry_title: 'Beach day',
          filename: 'photo.jpg',
          media_type: 'image',
          size: 2048,
        },
      ],
      total: 1,
    } as never)

    const { default: MediaTimelineView } = await import(
      './MediaTimelineView.vue'
    )
    const wrapper = mount(MediaTimelineView, {
      global: {
        plugins: [createPinia()],
        stubs: { MediaViewer: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('photo.jpg')
    wrapper.unmount()
  })
})
