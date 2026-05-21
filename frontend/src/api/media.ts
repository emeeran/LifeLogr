import { request, formDataRequest, API_ORIGIN } from './client'
import type { MediaResponse } from '../types'

export const mediaApi = {
  upload(entryId: number, file: File, caption?: string): Promise<MediaResponse> {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('entry_id', String(entryId))
    if (caption) fd.append('caption', caption)
    return formDataRequest('/media', fd)
  },

  get(id: number): Promise<MediaResponse> {
    return request(`/media/${id}`)
  },

  fileUrl(id: number): string {
    return `${API_ORIGIN}/api/v1/media/${id}/file`
  },

  delete(id: number): Promise<void> {
    return request(`/media/${id}`, { method: 'DELETE' })
  },

  listByEntry(entryId: number): Promise<MediaResponse[]> {
    return request(`/media/entry/${entryId}`)
  },
}
