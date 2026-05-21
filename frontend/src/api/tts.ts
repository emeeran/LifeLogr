import { API_ORIGIN } from './client'

export const ttsApi = {
  getVoice(): string {
    return localStorage.getItem('tts-voice') || 'en-US-AvaNeural'
  },

  entryUrl(entryId: number): string {
    return `${API_ORIGIN}/api/v1/tts/entry/${entryId}?voice=${encodeURIComponent(this.getVoice())}`
  },

  async speakBlob(text: string): Promise<Blob> {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: this.getVoice() }),
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(`TTS ${res.status}: ${detail}`)
    }
    return res.blob()
  },
}
