import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for NotesView.
 *
 * Guards against setup-order crashes (e.g. an eager `watch`/`computed` placed
 * above the refs it reads → "Cannot access 'x' before initialization") that
 * only show up when the component actually mounts.
 */

vi.mock('../../api/notes', () => ({
  notesApi: {
    list: vi.fn(async () => ({ items: [], total: 0 })),
    search: vi.fn(async () => ({ items: [], total: 0 })),
    listFolders: vi.fn(async () => []),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    createFolder: vi.fn(),
    deleteFolder: vi.fn(),
    importMarkdownFile: vi.fn(),
    uploadMedia: vi.fn(),
    uploadMediaFromPath: vi.fn(),
    mediaFileUrl: vi.fn(() => ''),
    listNoteMedia: vi.fn(async () => []),
    exportPageMarkdown: vi.fn(),
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

vi.mock('../../utils/fileDialog', () => ({
  pickFile: vi.fn(async () => null),
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

describe('NotesView mount', () => {
  it('mounts with an empty notebook store and renders the tree rail', async () => {
    const { default: NotesView } = await import('./NotesView.vue')
    const wrapper = mount(NotesView, {
      global: {
        plugins: [createPinia()],
        stubs: {
          NoteEditor: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    // The tree rail is virtualized (happy-dom has no layout, so it renders no
    // rows), but the main pane's empty state must be present.
    expect(wrapper.text()).toContain('Pick a note')
    wrapper.unmount()
  })

  it('mounts with notes + folders returned by the API', async () => {
    const { notesApi } = await import('../../api/notes')
    vi.mocked(notesApi.list).mockResolvedValue({
      items: [
        {
          id: 1,
          folder_id: 3,
          title: 'Pinned note',
          is_pinned: true,
          updated_at: '2026-01-02T00:00:00',
        },
      ],
      total: 1,
    } as never)
    vi.mocked(notesApi.listFolders).mockResolvedValue([
      { id: 3, name: 'Work', parent_id: null, note_count: 1 },
    ] as never)

    const { default: NotesView } = await import('./NotesView.vue')
    const wrapper = mount(NotesView, {
      global: {
        plugins: [createPinia()],
        stubs: {
          NoteEditor: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    wrapper.unmount()
  })
})
