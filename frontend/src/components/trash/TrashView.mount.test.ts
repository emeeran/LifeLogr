import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke + restore/purge interaction test for TrashView.
 *
 * The view must handle a loaded trash list, surface restore/purge affordances,
 * and gate "delete forever" behind the confirm dialog (it is irreversible).
 */

const trashMock = vi.fn(async () => ({
  items: [
    {
      id: 7,
      entry_date: '2026-11-01',
      title: 'Ridge walk',
      body_snippet: 'Notes about the hike.',
      mood: null,
      is_encrypted: false,
      tags: [{ id: 1, name: 'hiking' }],
      media_count: 2,
      has_recording: false,
      deleted_at: '2026-11-08T10:00:00Z',
      created_at: '2026-11-01T10:00:00Z',
    },
    {
      id: 9,
      entry_date: '2026-11-02',
      title: null,
      body_snippet: '',
      mood: null,
      is_encrypted: true,
      tags: [],
      media_count: 0,
      has_recording: true,
      deleted_at: '2026-11-08T11:00:00Z',
      created_at: '2026-11-02T10:00:00Z',
    },
  ],
  total: 2,
  offset: 0,
  limit: 50,
}))

vi.mock('../../api/entries', async () => {
  const { makeEntriesApiMock } = await import('../../test-utils/apiMocks')
  return { entriesApi: makeEntriesApiMock({ trash: trashMock }) }
})

vi.mock('../../api/media', async () => {
  const { makeMediaApiMock } = await import('../../test-utils/apiMocks')
  return { mediaApi: makeMediaApiMock() }
})

// The trash view's actions hit entriesApi only — no other API surface to mock.

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
})

async function mountView() {
  const { default: TrashView } = await import('./TrashView.vue')
  const wrapper = mount(TrashView)
  await flushPromises()
  return wrapper
}

describe('TrashView', () => {
  it('renders trashed entries with restore and delete-forever affordances', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).toContain('Ridge walk')
    expect(text).toContain('Encrypted')
    expect(text).toContain('#hiking')
    expect(wrapper.findAll('button[title="Restore entry"]')).toHaveLength(2)
    expect(wrapper.findAll('button[title="Delete forever"]')).toHaveLength(2)
    expect(trashMock).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('restore() calls the API and drops the row locally', async () => {
    const { entriesApi } = await import('../../api/entries')
    ;(entriesApi.restore as ReturnType<typeof vi.fn>).mockResolvedValue({})
    const wrapper = await mountView()
    await wrapper.findAll('button[title="Restore entry"]')[0].trigger('click')
    await flushPromises()
    expect(entriesApi.restore).toHaveBeenCalledWith(7)
    expect(wrapper.findAll('button[title="Restore entry"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('"delete forever" requires the confirm dialog before purging', async () => {
    const { entriesApi } = await import('../../api/entries')
    ;(entriesApi.purge as ReturnType<typeof vi.fn>).mockResolvedValue(undefined)
    const wrapper = await mountView()

    await wrapper.findAll('button[title="Delete forever"]')[0].trigger('click')
    await flushPromises()
    // Dialog is up; nothing purged yet.
    expect(wrapper.text()).toContain('This permanently destroys')
    expect(entriesApi.purge).not.toHaveBeenCalled()

    const dialogButton = (label: string) =>
      wrapper.findAll('button').find((b) => b.text().trim() === label)!
    await dialogButton('Cancel').trigger('click')
    await flushPromises()
    expect(entriesApi.purge).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('This permanently destroys')

    // Confirm path: reopen and confirm this time.
    await wrapper.findAll('button[title="Delete forever"]')[0].trigger('click')
    await flushPromises()
    await dialogButton('Confirm').trigger('click')
    await flushPromises()
    expect(entriesApi.purge).toHaveBeenCalledWith(7)
    wrapper.unmount()
  })
})
