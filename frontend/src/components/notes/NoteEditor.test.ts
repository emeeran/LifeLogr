import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { NoteResponse } from '../../types'

/**
 * Mount smoke test for NoteEditor.
 *
 * Guards against setup-order crashes that unit tests on pure helpers can't
 * see: a `watch(..., { immediate: true })` (or any eagerly-evaluated computed)
 * placed above the refs it reads throws "Cannot access 'x' before
 * initialization" during setup, and the editor silently fails to render —
 * notes stay listed in the sidebar but never open. If this test mounts, the
 * editor's setup ran to completion.
 */

vi.mock('../../api/notes', () => ({
  notesApi: {
    uploadMedia: vi.fn(),
    uploadMediaFromPath: vi.fn(),
    mediaFileUrl: vi.fn(() => ''),
    exportPageMarkdown: vi.fn(),
  },
}))
// Setup calls aiStatus() and the media list — mock so the test never emits
// real fetches (they log ECONNREFUSED noise under happy-dom).
vi.mock('../../api/ai', () => ({
  aiApi: { status: vi.fn().mockResolvedValue({}) },
}))
vi.mock('../../api/media', () => ({
  mediaApi: { listForNote: vi.fn().mockResolvedValue([]) },
}))

function makeNote(overrides: Partial<NoteResponse> = {}): NoteResponse {
  return {
    id: 1,
    folder_id: 1,
    title: 'Hello',
    body: '# Hi\n\nSome content',
    is_pinned: false,
    color: null,
    is_encrypted: false,
    encrypted_at: null,
    tags: [],
    pages: [],
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...overrides,
  } as NoteResponse
}

// happy-dom lacks a few browser APIs the editor's composables touch.
beforeEach(() => {
  setActivePinia(createPinia())
  // Hermetic network: child components/stores may fire setup fetches (they
  // resolve against happy-dom's localhost:3000 and log ECONNREFUSED noise).
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    }),
  )
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
})

describe('NoteEditor mount', () => {
  it('mounts a plain note without throwing during setup', async () => {
    const { default: NoteEditor } = await import('./NoteEditor.vue')
    const wrapper = mount(NoteEditor, {
      props: { note: makeNote(), folders: [], allTags: [] },
      global: {
        plugins: [createPinia()],
        stubs: {
          AiDrawerPanel: true,
          SnipOverlay: true,
          WebClipModal: true,
          MediaViewer: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()
    expect(wrapper.vm).toBeTruthy()
    // The exposed dirty flag resolves (not a TDZ crash) and starts clean.
    expect((wrapper.vm as { isDirty: boolean }).isDirty).toBe(false)
    wrapper.unmount()
  })

  it('mounts a multi-page note (pages render as tabs)', async () => {
    const { default: NoteEditor } = await import('./NoteEditor.vue')
    const note = makeNote({
      pages: [
        {
          id: 7,
          note_id: 1,
          title: 'Page B',
          body: 'page body',
          sort_order: 1,
          created_at: '2026-01-01T00:00:00',
          updated_at: '2026-01-01T00:00:00',
        },
      ],
    } as Partial<NoteResponse>)
    const wrapper = mount(NoteEditor, {
      props: { note, folders: [], allTags: [] },
      global: {
        plugins: [createPinia()],
        stubs: {
          AiDrawerPanel: true,
          SnipOverlay: true,
          WebClipModal: true,
          MediaViewer: true,
          Teleport: true,
        },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Page B')
    wrapper.unmount()
  })
})
