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

  entryUrl(entryId: number): string {
    return `${API_ORIGIN}/api/v1/tts/entry/${entryId}?voice=${encodeURIComponent(this.getVoice())}&rate=${this.getSpeed()}&volume=${this.getVolume()}`
  },

  async speakBlob(text: string): Promise<Blob> {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: this.getVoice(),
        rate: this.getSpeed(),
        volume: this.getVolume(),
      }),
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(`TTS ${res.status}: ${detail}`)
    }
    return res.blob()
  },
}
