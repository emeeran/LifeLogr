import { request, API_ORIGIN } from './client'
import type {
  NoteResponse,
  NoteCreate,
  NoteUpdate,
  NoteListResponse,
  NoteListParams,
  NoteFolderResponse,
  NoteFolderCreate,
  NoteFolderUpdate,
  NoteEncryptionStatusResponse,
  NoteMediaResponse,
  NotePageResponse,
  NotePageCreate,
  NotePageUpdate,
  NotePageReorderItem,
} from '../types'

export const notesApi = {
  create(data: NoteCreate): Promise<NoteResponse> {
    return request('/notes', { method: 'POST', body: JSON.stringify(data) })
  },

  get(id: number): Promise<NoteResponse> {
    return request(`/notes/${id}`)
  },

  list(params?: NoteListParams): Promise<NoteListResponse> {
    const sp = new URLSearchParams()
    if (params?.offset != null) sp.set('offset', String(params.offset))
    if (params?.limit != null) sp.set('limit', String(params.limit))
    if (params?.folder_id != null) sp.set('folder_id', String(params.folder_id))
    if (params?.tag_ids?.length) params.tag_ids.forEach((t) => sp.append('tag_ids', String(t)))
    if (params?.is_pinned != null) sp.set('is_pinned', String(params.is_pinned))
    const qs = sp.toString()
    return request(`/notes${qs ? `?${qs}` : ''}`)
  },

  search(query: string, offset = 0, limit = 20): Promise<NoteListResponse> {
    return request(`/notes/search?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`)
  },

  update(id: number, data: NoteUpdate): Promise<NoteResponse> {
    return request(`/notes/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
  },

  delete(id: number): Promise<void> {
    return request(`/notes/${id}`, { method: 'DELETE' })
  },

  restore(id: number): Promise<NoteResponse> {
    return request(`/notes/${id}/restore`, { method: 'POST' })
  },

  setPinned(id: number, is_pinned: boolean): Promise<NoteResponse> {
    return request(`/notes/${id}/pin`, { method: 'PATCH', body: JSON.stringify({ is_pinned }) })
  },

  // ── Sub-pages (EPIM-style page tabs) ──
  createPage(noteId: number, data: NotePageCreate): Promise<NotePageResponse> {
    return request(`/notes/${noteId}/pages`, { method: 'POST', body: JSON.stringify(data) })
  },
  updatePage(noteId: number, pageId: number, data: NotePageUpdate): Promise<NotePageResponse> {
    return request(`/notes/${noteId}/pages/${pageId}`, { method: 'PATCH', body: JSON.stringify(data) })
  },
  deletePage(noteId: number, pageId: number): Promise<void> {
    return request(`/notes/${noteId}/pages/${pageId}`, { method: 'DELETE' })
  },
  reorderPages(noteId: number, items: NotePageReorderItem[]): Promise<{ reordered: number }> {
    return request(`/notes/${noteId}/pages/reorder`, { method: 'POST', body: JSON.stringify({ items }) })
  },

  listFolders(): Promise<NoteFolderResponse[]> {
    return request('/notes/folders')
  },

  createFolder(data: NoteFolderCreate): Promise<NoteFolderResponse> {
    return request('/notes/folders', { method: 'POST', body: JSON.stringify(data) })
  },

  updateFolder(id: number, data: NoteFolderUpdate): Promise<NoteFolderResponse> {
    return request(`/notes/folders/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
  },

  deleteFolder(id: number): Promise<void> {
    return request(`/notes/folders/${id}`, { method: 'DELETE' })
  },

  encrypt(id: number, passphrase: string): Promise<NoteEncryptionStatusResponse> {
    return request(`/notes/${id}/encryption/encrypt`, {
      method: 'POST',
      body: JSON.stringify({ passphrase }),
    })
  },

  decrypt(id: number, passphrase: string): Promise<NoteEncryptionStatusResponse> {
    return request(`/notes/${id}/encryption/decrypt`, {
      method: 'POST',
      body: JSON.stringify({ passphrase }),
    })
  },

  encryptionStatus(id: number): Promise<NoteEncryptionStatusResponse> {
    return request(`/notes/${id}/encryption/status`)
  },

  uploadMedia(noteId: number, file: File, caption?: string): Promise<NoteMediaResponse> {
    const form = new FormData()
    form.append('file', file)
    if (caption) form.append('caption', caption)
    return request(`/notes/${noteId}/media`, { method: 'POST', body: form })
  },

  uploadMediaFromPath(noteId: number, path: string, caption?: string): Promise<NoteMediaResponse> {
    return request(`/notes/${noteId}/media/from-path`, {
      method: 'POST',
      body: JSON.stringify({ path, caption }),
    })
  },

  listNoteMedia(noteId: number): Promise<NoteMediaResponse[]> {
    return request(`/notes/${noteId}/media`)
  },

  deleteNoteMedia(noteId: number, mediaId: number): Promise<void> {
    return request(`/notes/${noteId}/media/${mediaId}`, { method: 'DELETE' })
  },

  mediaFileUrl(noteId: number, mediaId: number): string {
    return `${API_ORIGIN}/api/v1/notes/${noteId}/media/${mediaId}/file`
  },
}
