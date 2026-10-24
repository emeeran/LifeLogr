import { request, blobRequest, API_ORIGIN } from './client'

export const ttsApi = {
  getVoice(): string {
    return localStorage.getItem('lifelogr-tts-voice') || 'en-US-AvaNeural'
  },

  getSpeed(): number {
    return parseFloat(localStorage.getItem('lifelogr-tts-speed') || '1.0')
  },

  getVolume(): number {
    return parseInt(localStorage.getItem('lifelogr-tts-volume') || '100')
  },

  /** Pitch offset in Hz (0 = unchanged). Lower = deeper, warmer. */
  getPitch(): number {
    return parseInt(localStorage.getItem('lifelogr-tts-pitch') || '0')
  },

  /** Prosody query string shared by all synth/play URLs. */
  paramQuery(): string {
    return `voice=${encodeURIComponent(this.getVoice())}&rate=${this.getSpeed()}&volume=${this.getVolume()}&pitch=${this.getPitch()}`
  },

  /** GET URL for an entry's cached audio (kept for prewarm/diagnostics). */
  entryUrl(entryId: number): string {
    return `${API_ORIGIN}/api/v1/tts/entry/${entryId}?${this.paramQuery()}`
  },

  /** Fetch an entry's audio as a blob object URL. Synthesis failures surface
   *  as `ApiError` (the backend 422s when there's no readable text, 502 when
   *  Edge TTS is unreachable) instead of the audio element's opaque
   *  "no supported source" MediaError. Blob URLs stay fully seekable. */
  async entryAudioUrl(entryId: number): Promise<string> {
    const blob = await blobRequest(`/tts/entry/${entryId}?${this.paramQuery()}`)
    return URL.createObjectURL(blob)
  },

  /** GET URL for a previously-synthesized text audio file (key from speakUrl). */
  fileUrl(key: string): string {
    return `${API_ORIGIN}/api/v1/tts/file/${key}`
  },

  /** Synthesize text to cache and return its key (play via fileUrl(key)). */
  speakUrl(text: string): Promise<{ key: string }> {
    return request('/tts/speak', {
      method: 'POST',
      body: JSON.stringify({
        text,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
  },

  /** Background pre-generation for an entry (fire-and-forget; caller swallows errors). */
  prewarmEntry(entryId: number): Promise<void> {
    return request('/tts/prewarm', {
      method: 'POST',
      body: JSON.stringify({
        entry_id: entryId,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
  },

  /** Background pre-generation for arbitrary text (fire-and-forget; caller swallows errors). */
  prewarmText(text: string): Promise<void> {
    return request('/tts/prewarm', {
      method: 'POST',
      body: JSON.stringify({
        text,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
  },
}
