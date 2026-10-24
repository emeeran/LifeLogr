import { request, formDataRequest } from './client'
import type { VoiceRecordingResponse } from '../types'

export const recordingsApi = {
  upload(entryId: number, file: File): Promise<VoiceRecordingResponse> {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('entry_id', String(entryId))
    return formDataRequest('/recordings', fd)
  },

  /** Begin backend-side microphone capture (sounddevice/PortAudio). */
  start(entryId: number): Promise<{ ok: boolean; entry_id: number }> {
    const fd = new FormData()
    fd.append('entry_id', String(entryId))
    return formDataRequest('/recordings/start', fd)
  },

  /** Stop the active capture; the backend encodes it to Ogg/Vorbis and returns it.
   *
   * Sent as FormData (a CORS "simple" request) — deliberately matching `start`.
   * A body-less `Content-Type: application/json` POST would trigger a CORS
   * preflight, which WebKit2GTK (the Tauri webview) mishandles for loopback,
   * surfacing as "Load failed". FormData avoids the preflight entirely. */
  stop(): Promise<VoiceRecordingResponse> {
    return formDataRequest('/recordings/stop', new FormData())
  },

  listByEntry(entryId: number): Promise<VoiceRecordingResponse[]> {
    return request(`/recordings/entry/${entryId}`)
  },

  get(id: number): Promise<VoiceRecordingResponse> {
    return request(`/recordings/${id}`)
  },

  delete(id: number): Promise<void> {
    return request(`/recordings/${id}`, { method: 'DELETE' })
  },
}
