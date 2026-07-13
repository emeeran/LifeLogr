import { API_ORIGIN } from './client'

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

  /** GET URL for an entry's cached audio — Range-capable, usable directly as <audio src>. */
  entryUrl(entryId: number): string {
    return `${API_ORIGIN}/api/v1/tts/entry/${entryId}?${this.paramQuery()}`
  },

  /** GET URL for a previously-synthesized text audio file (key from speakUrl). */
  fileUrl(key: string): string {
    return `${API_ORIGIN}/api/v1/tts/file/${key}`
  },

  /** Synthesize text to cache and return its key (play via fileUrl(key)). */
  async speakUrl(text: string): Promise<{ key: string }> {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(`TTS ${res.status}: ${detail}`)
    }
    return res.json()
  },

  /** Background pre-generation for an entry (fire-and-forget; caller swallows errors). */
  async prewarmEntry(entryId: number): Promise<void> {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/prewarm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_id: entryId,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
    if (!res.ok) throw new Error(`TTS prewarm ${res.status}`)
  },

  /** Background pre-generation for arbitrary text (fire-and-forget; caller swallows errors). */
  async prewarmText(text: string): Promise<void> {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/prewarm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
        pitch: this.getPitch(),
      }),
    })
    if (!res.ok) throw new Error(`TTS prewarm ${res.status}`)
  },
}
