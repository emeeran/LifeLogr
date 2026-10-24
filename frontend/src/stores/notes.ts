import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type {
  NoteResponse,
  NoteListItem,
  NoteFolderResponse,
  NoteCreate,
  NoteUpdate,
  NoteListParams,
  NotePageCreate,
  NotePageUpdate,
  NotePageReorderItem,
  NotePageResponse,
} from '../types'
import { notesApi } from '../api/notes'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

/** Map a full note (from create/update) to the lightweight list-item shape
 *  (body -> truncated snippet, pages dropped) for optimistic list updates. */
function toListItem(note: NoteResponse): NoteListItem {
  const { body, pages: _pages, ...rest } = note
  return { ...rest, body_snippet: body.slice(0, 300) }
}

/** Page size for the list fetches. The tree is virtualized, so the store loads
 *  every page rather than capping the visible list at one page. Must stay at
 *  or below the backend's `le=100` cap on the `limit` query param. */
const PAGE_SIZE = 100
/** Hard stop so a misbehaving `total` can never loop forever. */
const MAX_NOTES = 10_000

export const useNotesStore = defineStore('notes', () => {
  const notes = shallowRef<NoteListItem[]>([])
  const folders = shallowRef<NoteFolderResponse[]>([])
  const currentNote = ref<NoteResponse | null>(null)
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Failures are surfaced app-wide through the toast host (the store's `error`
  // ref stays for state/tests, but is no longer the only place they land).
  function fail(fallback: string, e: unknown, toastMessage?: string) {
    const message = errorMessage(e) || fallback
    error.value = message
    useToastStore().error(`${toastMessage ?? fallback}: ${message}`)
  }

  /** Fetch every note (all pages) into `notes`. The tree/list is virtualized,
   *  so the header's true total and the rendered list always agree — the old
   *  `limit: 100` fetch silently hid everything past the first hundred. */
  async function fetchNotes(params?: NoteListParams) {
    loading.value = true
    error.value = null
    try {
      // Explicit params (filters, search-style narrow queries) behave as before.
      if (params && (params.offset != null || params.limit != null)) {
        const res = await notesApi.list(params)
        notes.value = res.items
        total.value = res.total
        return
      }
      const first = await notesApi.list({ offset: 0, limit: PAGE_SIZE })
      const items = [...first.items]
      total.value = first.total
      let offset = PAGE_SIZE
      while (
        items.length < Math.min(first.total, MAX_NOTES) &&
        offset < MAX_NOTES
      ) {
        const res = await notesApi.list({ offset, limit: PAGE_SIZE })
        if (!res.items.length) break // server stopped returning — don't spin
        items.push(...res.items)
        offset += PAGE_SIZE
      }
      notes.value = items
    } catch (e: unknown) {
      fail('Failed to load notes', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchFolders() {
    try {
      folders.value = await notesApi.listFolders()
    } catch (e: unknown) {
      fail('Failed to load folders', e)
    }
  }

  async function selectNote(id: number | null) {
    if (id == null) {
      currentNote.value = null
      return
    }
    try {
      currentNote.value = await notesApi.get(id)
    } catch (e: unknown) {
      fail('Failed to load note', e)
    }
  }

  async function createNote(data: NoteCreate) {
    error.value = null
    try {
      return await notesApi.create(data)
    } catch (e: unknown) {
      fail('Failed to create note', e)
      throw e
    }
  }

  async function updateNote(id: number, data: NoteUpdate) {
    error.value = null
    try {
      const note = await notesApi.update(id, data)
      notes.value = notes.value.map((n) => (n.id === id ? toListItem(note) : n))
      if (currentNote.value?.id === id) currentNote.value = note
      return note
    } catch (e: unknown) {
      fail('Failed to save note', e)
      throw e
    }
  }

  async function deleteNote(id: number) {
    error.value = null
    try {
      await notesApi.delete(id)
      notes.value = notes.value.filter((n) => n.id !== id)
      if (currentNote.value?.id === id) currentNote.value = null
    } catch (e: unknown) {
      fail('Failed to delete note', e)
      throw e
    }
  }

  async function togglePin(id: number, is_pinned: boolean) {
    error.value = null
    try {
      const note = await notesApi.setPinned(id, is_pinned)
      notes.value = notes.value.map((n) => (n.id === id ? toListItem(note) : n))
      if (currentNote.value?.id === id) currentNote.value = note
      return note
    } catch (e: unknown) {
      fail('Failed to pin note', e)
      throw e
    }
  }

  async function createFolder(name: string, parentId?: number | null) {
    error.value = null
    try {
      await notesApi.createFolder({ name, parent_id: parentId ?? null })
      await fetchFolders()
    } catch (e: unknown) {
      fail('Failed to create notebook', e)
      throw e
    }
  }

  async function deleteFolder(id: number) {
    error.value = null
    try {
      await notesApi.deleteFolder(id)
      await fetchFolders()
    } catch (e: unknown) {
      fail('Failed to delete notebook', e)
      throw e
    }
  }

  // ── Sub-pages (EPIM-style page tabs) ──────────────────────────────────────
  // Pages belong to the active note; CRUD updates currentNote.pages in place.
  function _patchPages(fn: (pages: NotePageResponse[]) => NotePageResponse[]) {
    if (!currentNote.value) return
    currentNote.value = {
      ...currentNote.value,
      pages: fn(currentNote.value.pages),
    }
  }

  async function createPage(
    data: NotePageCreate,
  ): Promise<NotePageResponse | null> {
    if (!currentNote.value) return null
    error.value = null
    try {
      const page = await notesApi.createPage(currentNote.value.id, data)
      _patchPages((pages) => [...pages, page])
      return page
    } catch (e: unknown) {
      fail('Failed to create page', e)
      throw e
    }
  }

  async function updatePage(
    pageId: number,
    data: NotePageUpdate,
  ): Promise<void> {
    if (!currentNote.value) return
    error.value = null
    try {
      const page = await notesApi.updatePage(currentNote.value.id, pageId, data)
      _patchPages((pages) => pages.map((p) => (p.id === pageId ? page : p)))
    } catch (e: unknown) {
      fail('Failed to save page', e)
      throw e
    }
  }

  async function deletePage(pageId: number): Promise<void> {
    if (!currentNote.value) return
    error.value = null
    try {
      await notesApi.deletePage(currentNote.value.id, pageId)
      _patchPages((pages) => pages.filter((p) => p.id !== pageId))
    } catch (e: unknown) {
      fail('Failed to delete page', e)
      throw e
    }
  }

  async function reorderPages(items: NotePageReorderItem[]): Promise<void> {
    if (!currentNote.value) return
    error.value = null
    try {
      await notesApi.reorderPages(currentNote.value.id, items)
      const order = new Map(items.map((i) => [i.id, i.sort_order]))
      _patchPages((pages) =>
        [...pages].sort(
          (a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0),
        ),
      )
    } catch (e: unknown) {
      fail('Failed to reorder pages', e)
      throw e
    }
  }

  return {
    notes,
    folders,
    currentNote,
    total,
    loading,
    error,
    fetchNotes,
    fetchFolders,
    selectNote,
    createNote,
    updateNote,
    deleteNote,
    togglePin,
    createFolder,
    deleteFolder,
    createPage,
    updatePage,
    deletePage,
    reorderPages,
  }
})
