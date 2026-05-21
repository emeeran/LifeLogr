import { request, formDataRequest } from './client'
import type { VoiceRecordingResponse } from '../types'

export const recordingsApi = {
  upload(entryId: number, file: File): Promise<VoiceRecordingResponse> {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('entry_id', String(entryId))
    return formDataRequest('/recordings', fd)
  },

  listByEntry(entryId: number): Promise<VoiceRecordingResponse[]> {
    return request(`/recordings/entry/${entryId}`)
  },

  transcribe(id: number): Promise<VoiceRecordingResponse> {
    return request(`/recordings/${id}/transcribe`, { method: 'POST' })
  },

  get(id: number): Promise<VoiceRecordingResponse> {
    return request(`/recordings/${id}`)
  },

  delete(id: number): Promise<void> {
    return request(`/recordings/${id}`, { method: 'DELETE' })
  },
}
