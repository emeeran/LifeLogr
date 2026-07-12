import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type {
  NoteResponse,
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

export const useNotesStore = defineStore('notes', () => {
  const notes = shallowRef<NoteResponse[]>([])
  const folders = shallowRef<NoteFolderResponse[]>([])
  const currentNote = ref<NoteResponse | null>(null)
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchNotes(params?: NoteListParams) {
    loading.value = true
    error.value = null
    try {
      const res = await notesApi.list(params)
      notes.value = res.items
      total.value = res.total
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load notes'
    } finally {
      loading.value = false
    }
  }

  async function fetchFolders() {
    try {
      folders.value = await notesApi.listFolders()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load folders'
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
      error.value = e instanceof Error ? e.message : 'Failed to load note'
    }
  }

  async function createNote(data: NoteCreate) {
    error.value = null
    try {
      return await notesApi.create(data)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to create note'
      throw e
    }
  }

  async function updateNote(id: number, data: NoteUpdate) {
    error.value = null
    try {
      const note = await notesApi.update(id, data)
      notes.value = notes.value.map((n) => (n.id === id ? note : n))
      if (currentNote.value?.id === id) currentNote.value = note
      return note
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to update note'
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
      error.value = e instanceof Error ? e.message : 'Failed to delete note'
      throw e
    }
  }

  async function togglePin(id: number, is_pinned: boolean) {
    error.value = null
    try {
      const note = await notesApi.setPinned(id, is_pinned)
      notes.value = notes.value.map((n) => (n.id === id ? note : n))
      if (currentNote.value?.id === id) currentNote.value = note
      return note
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to pin note'
      throw e
    }
  }

  async function createFolder(name: string) {
    error.value = null
    try {
      await notesApi.createFolder({ name })
      await fetchFolders()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to create folder'
      throw e
    }
  }

  async function deleteFolder(id: number) {
    error.value = null
    try {
      await notesApi.deleteFolder(id)
      await fetchFolders()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to delete folder'
      throw e
    }
  }

  // ── Sub-pages (EPIM-style page tabs) ──────────────────────────────────────
  // Pages belong to the active note; CRUD updates currentNote.pages in place.
  function _patchPages(fn: (pages: NotePageResponse[]) => NotePageResponse[]) {
    if (!currentNote.value) return
    currentNote.value = { ...currentNote.value, pages: fn(currentNote.value.pages) }
  }

  async function createPage(data: NotePageCreate): Promise<NotePageResponse | null> {
    if (!currentNote.value) return null
    error.value = null
    try {
      const page = await notesApi.createPage(currentNote.value.id, data)
      _patchPages((pages) => [...pages, page])
      return page
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to create page'
      throw e
    }
  }

  async function updatePage(pageId: number, data: NotePageUpdate): Promise<void> {
    if (!currentNote.value) return
    error.value = null
    try {
      const page = await notesApi.updatePage(currentNote.value.id, pageId, data)
      _patchPages((pages) => pages.map((p) => (p.id === pageId ? page : p)))
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to update page'
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
      error.value = e instanceof Error ? e.message : 'Failed to delete page'
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
        [...pages].sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0)),
      )
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to reorder pages'
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
