import { request, formDataRequest, API_ORIGIN } from './client'
import type { MediaResponse, MediaTimelineResponse } from '../types'

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

  /** Extract text from an image attachment via OCR (tesseract). */
  extractText(id: number): Promise<{ text: string }> {
    return request(`/media/${id}/ocr`, { method: 'POST' })
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

  listAll(params: { offset?: number; limit?: number; media_type?: string }): Promise<MediaTimelineResponse> {
    const qs = new URLSearchParams()
    if (params.offset !== undefined) qs.set('offset', String(params.offset))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.media_type) qs.set('media_type', params.media_type)
    return request(`/media/all?${qs.toString()}`)
  },
}
