import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for CalendarGrid — setup-order / mount-crash guard.
 */

vi.mock('../../api/entries', () => ({
  entriesApi: {
    calendarMonth: vi.fn(async () => []),
    list: vi.fn(async () => ({ items: [], total: 0 })),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
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

describe('CalendarGrid mount', () => {
  it('mounts an empty month without throwing during setup', async () => {
    const [{ default: CalendarGrid }, { default: CalendarCell }] = await
      Promise.all([import('./CalendarGrid.vue'), import('./CalendarCell.vue')])
    const wrapper = mount(CalendarGrid, {
      global: {
        plugins: [createPinia()],
        stubs: { GoToDateModal: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    // The month grid always lays out its cells (35-42), even when empty.
    expect(wrapper.findAllComponents(CalendarCell).length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('mounts with month entries and renders them in their cells', async () => {
    const { entriesApi } = await import('../../api/entries')
    const now = new Date()
    vi.mocked(entriesApi.calendarMonth).mockResolvedValue([
      {
        id: 7,
        title: 'Beach day',
        body: '',
        entry_date: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-04`,
        tags: [],
      },
    ] as never)

    const { default: CalendarGrid } = await import('./CalendarGrid.vue')
    const wrapper = mount(CalendarGrid, {
      global: {
        plugins: [createPinia()],
        stubs: { GoToDateModal: true, Teleport: true },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('Beach day')
    wrapper.unmount()
  })
})
