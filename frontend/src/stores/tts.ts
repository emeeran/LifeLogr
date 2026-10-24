import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ttsApi } from '../api/tts'
import { errMsg } from '../utils/errorMessage.ts'

/**
 * App-wide read-aloud player.
 *
 * Owns a single HTMLAudioElement and all transport state. Every read-aloud
 * button (entry, editor, note) drives this one player so only one stream
 * plays at a time and behaviour is consistent. Audio is served Range-capable
 * from the backend's TTS cache (FileResponse), so playback starts on first
 * bytes and is seekable; background prewarm makes the common path instant.
 *
 * Components drive it via toggleEntry(id) / toggleText(text) and read button
 * state via isPlayingEntry(id) / isPlayingText(text) (and the *Loading peers).
 */

export interface TtsSource {
  kind: 'entry' | 'text'
  entryId?: number
  textKey?: string
}

/** Cheap stable string hash (djb2) — only used to match "is this text playing". */
function hashStr(s: string): string {
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0
  return (h >>> 0).toString(16)
}

// One module-level audio element shared across the app.
let audioEl: HTMLAudioElement | null = null
let wired = false
/** Blob object URL handed to the audio element, if the current source is one. */
let currentObjectUrl: string | null = null

function ensureAudio(): HTMLAudioElement {
  if (!audioEl) audioEl = new Audio()
  return audioEl
}

/** Map a MediaError to something a user can act on — the raw message for the
 *  common "source not supported" case is browser jargon with no next step. */
function describeMediaError(a: HTMLAudioElement): string {
  const e = a.error
  if (!e) return 'Playback failed'
  if (e.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)
    return 'Audio source unavailable or unsupported'
  if (e.code === MediaError.MEDIA_ERR_NETWORK) return 'Network error during playback'
  if (e.code === MediaError.MEDIA_ERR_DECODE) return 'Audio could not be decoded'
  if (e.code === MediaError.MEDIA_ERR_ABORTED) return 'Playback aborted'
  return 'Playback failed'
}

function clearObjectUrl() {
  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl)
    currentObjectUrl = null
  }
}

export const useTtsStore = defineStore('tts', () => {
  const isPlaying = ref(false)
  const isLoading = ref(false)
  const lastError = ref<string | null>(null)
  const current = ref<TtsSource | null>(null)
  // Progress/duration exposed for a future now-playing bar (no UI in v1).
  const currentTime = ref(0)
  const duration = ref(0)

  function wireEvents(a: HTMLAudioElement) {
    if (wired) return
    wired = true
    a.addEventListener('playing', () => {
      isPlaying.value = true
      isLoading.value = false
    })
    a.addEventListener('pause', () => {
      isPlaying.value = false
    })
    a.addEventListener('ended', () => {
      isPlaying.value = false
      current.value = null
      currentTime.value = 0
      clearObjectUrl()
    })
    a.addEventListener('timeupdate', () => {
      currentTime.value = a.currentTime
    })
    a.addEventListener('durationchange', () => {
      duration.value = isFinite(a.duration) ? a.duration : 0
    })
    a.addEventListener('error', () => {
      isPlaying.value = false
      isLoading.value = false
      lastError.value = describeMediaError(a)
    })
  }

  /** Stop and detach the current stream so a new one can start clean. */
  function resetStream() {
    const a = audioEl
    if (a) {
      a.pause()
      a.removeAttribute('src')
      a.load()
    }
    clearObjectUrl()
    isPlaying.value = false
    currentTime.value = 0
    duration.value = 0
  }

  /** Resolve the playable URL, then load+play it on the shared element. */
  async function playSource(src: TtsSource, resolveUrl: () => Promise<string>) {
    const a = ensureAudio()
    wireEvents(a)
    resetStream()
    current.value = src
    isLoading.value = true
    lastError.value = null
    try {
      const url = await resolveUrl()
      a.src = url
      await a.play()
    } catch (e: unknown) {
      // AbortError fires when a new load interrupts an in-flight play() — harmless.
      if (e instanceof DOMException && e.name === 'AbortError') return
      isPlaying.value = false
      isLoading.value = false
      current.value = null
      lastError.value = errMsg(e)
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function playEntry(entryId: number) {
    await playSource({ kind: 'entry', entryId }, async () => {
      currentObjectUrl = await ttsApi.entryAudioUrl(entryId)
      return currentObjectUrl
    })
  }

  async function playText(text: string) {
    const textKey = hashStr(text)
    await playSource({ kind: 'text', textKey }, async () => {
      const { key } = await ttsApi.speakUrl(text)
      if (!key) throw new Error('Nothing to read aloud')
      return ttsApi.fileUrl(key)
    })
  }

  function stop() {
    resetStream()
    current.value = null
    isLoading.value = false
  }

  /** Toggle an entry's audio: stop if it's currently active, else play. Rethrows on error. */
  async function toggleEntry(entryId: number) {
    if (isActiveEntry(entryId)) {
      stop()
      return
    }
    await playEntry(entryId)
  }

  /** Toggle arbitrary text's audio: stop if active, else play. Rethrows on error. */
  async function toggleText(text: string) {
    const k = hashStr(text)
    if (isActiveTextKey(k)) {
      stop()
      return
    }
    await playText(text)
  }

  function seek(t: number) {
    if (audioEl) audioEl.currentTime = t
  }

  function isActiveEntry(entryId: number): boolean {
    const c = current.value
    return (
      !!c &&
      c.kind === 'entry' &&
      c.entryId === entryId &&
      (isPlaying.value || isLoading.value)
    )
  }
  function isActiveText(text: string): boolean {
    return isActiveTextKey(hashStr(text))
  }
  function isActiveTextKey(k: string): boolean {
    const c = current.value
    return (
      !!c &&
      c.kind === 'text' &&
      c.textKey === k &&
      (isPlaying.value || isLoading.value)
    )
  }

  function isPlayingEntry(entryId: number): boolean {
    const c = current.value
    return !!c && c.kind === 'entry' && c.entryId === entryId && isPlaying.value
  }
  function isLoadingEntry(entryId: number): boolean {
    const c = current.value
    return !!c && c.kind === 'entry' && c.entryId === entryId && isLoading.value
  }
  function isPlayingText(text: string): boolean {
    const c = current.value
    return (
      !!c && c.kind === 'text' && c.textKey === hashStr(text) && isPlaying.value
    )
  }
  function isLoadingText(text: string): boolean {
    const c = current.value
    return (
      !!c && c.kind === 'text' && c.textKey === hashStr(text) && isLoading.value
    )
  }

  /** Background pre-generation — best-effort, swallows network errors (offline = silent). */
  async function prewarmEntry(entryId: number) {
    try {
      await ttsApi.prewarmEntry(entryId)
    } catch {
      /* offline / network — silent */
    }
  }
  async function prewarmText(text: string) {
    if (!text.trim()) return
    try {
      await ttsApi.prewarmText(text)
    } catch {
      /* silent */
    }
  }

  return {
    isPlaying,
    isLoading,
    lastError,
    current,
    currentTime,
    duration,
    playEntry,
    playText,
    stop,
    toggleEntry,
    toggleText,
    seek,
    isActiveEntry,
    isActiveText,
    isPlayingEntry,
    isLoadingEntry,
    isPlayingText,
    isLoadingText,
    prewarmEntry,
    prewarmText,
  }
})
