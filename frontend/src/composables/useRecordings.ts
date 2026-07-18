import { ref, computed, watch, onUnmounted, inject, provide, type InjectionKey, type ComputedRef, type Ref } from 'vue'
import { errMsg } from '../utils/error'
import { recordingsApi } from '../api/recordings'
import { API_ORIGIN } from '../api/client'
import type { VoiceRecordingResponse } from '../types'

export interface RecordingsApi {
  /** Persisted recordings for the active entry. */
  recordings: Ref<VoiceRecordingResponse[]>
  loadRecordings: () => Promise<void>

  /** Capture lifecycle. */
  recording: Ref<boolean>
  elapsed: Ref<number>
  uploading: Ref<boolean>
  hasEntry: ComputedRef<boolean>
  toggleRecord: () => Promise<void>

  /** Playback state (shared so the embedded list + floating player stay in sync). */
  activeId: Ref<number | null>
  active: ComputedRef<VoiceRecordingResponse | null>
  isPlaying: Ref<boolean>
  current: Ref<number>
  duration: Ref<number>
  togglePlay: (rec: VoiceRecordingResponse) => void
  seek: (t: number) => void
  closePlayback: () => void
  remove: (rec: VoiceRecordingResponse) => void
}

/**
 * Centralised recording + playback state for the active entry.
 *
 * Capture runs in the BACKEND (sounddevice → Ogg/Vorbis) — the webview's
 * MediaRecorder is unreliable in the packaged WebKit2GTK build. We only drive
 * the capture remotely and keep a local timer + playback <audio> for the UI.
 *
 * `entryIdRef` is a getter so the composable reacts to entry switches; entries
 * are id `-1` (new/unsaved) until persisted, so every op guards on `hasEntry`.
 */
export function useRecordings(
  entryIdRef: () => number | null,
  ensureSaved: () => Promise<boolean>,
): RecordingsApi {
  const recordings = ref<VoiceRecordingResponse[]>([])
  const recording = ref(false)
  const elapsed = ref(0)
  const uploading = ref(false)

  const activeId = ref<number | null>(null)
  const isPlaying = ref(false)
  const current = ref(0)
  const duration = ref(0)
  let audioEl: HTMLAudioElement | null = null

  let timer: ReturnType<typeof setInterval> | null = null
  function clearTimer() {
    if (timer) { clearInterval(timer); timer = null }
  }

  const hasEntry = computed(() => {
    const id = entryIdRef()
    return id != null && id > 0
  })

  const active = computed(
    () => recordings.value.find((r) => r.id === activeId.value) ?? null,
  )

  async function loadRecordings() {
    const id = entryIdRef()
    if (!id || id <= 0) { recordings.value = []; return }
    try {
      recordings.value = await recordingsApi.listByEntry(id)
    } catch { /* entry may have no recordings yet */ }
  }

  async function toggleRecord() {
    if (recording.value || uploading.value) {
      await stop()
      return
    }
    // A persisted entry is required before the backend can attach a recording.
    if (!hasEntry.value) {
      const ok = await ensureSaved()
      if (!ok) {
        alert('Please save this entry first, then record.')
        return
      }
    }
    recording.value = true
    elapsed.value = 0
    timer = setInterval(() => { elapsed.value++ }, 1000)
    try {
      await recordingsApi.start(entryIdRef()!)
    } catch (e: unknown) {
      clearTimer()
      recording.value = false
      const msg = errMsg(e)
      alert(`Could not start recording: ${msg}\n\nCheck that a microphone is connected.`)
    }
  }

  async function stop() {
    clearTimer()
    const wasRecording = recording.value
    recording.value = false
    if (!wasRecording) return
    uploading.value = true
    try {
      const rec = await recordingsApi.stop()
      recordings.value.push(rec)
    } catch (e: unknown) {
      const msg = errMsg(e)
      alert(`Recording failed: ${msg}`)
    } finally {
      uploading.value = false
    }
  }

  function closePlayback() {
    if (audioEl) { audioEl.pause(); audioEl.src = ''; audioEl = null }
    activeId.value = null
    isPlaying.value = false
    current.value = 0
    duration.value = 0
  }

  function bindAudio(a: HTMLAudioElement) {
    a.addEventListener('timeupdate', () => { current.value = a.currentTime })
    a.addEventListener('loadedmetadata', () => {
      if (Number.isFinite(a.duration)) duration.value = a.duration
    })
    a.addEventListener('durationchange', () => {
      if (Number.isFinite(a.duration)) duration.value = a.duration
    })
    a.addEventListener('ended', () => { isPlaying.value = false; current.value = 0 })
    a.addEventListener('error', () => {
      const err = a.error
      // Network error (code 2) usually means the file is missing on disk.
      const msg = err && err.code === 2
        ? 'This recording file is missing from disk.'
        : 'Playback failed for this recording.'
      closePlayback()
      alert(msg)
    })
  }

  function togglePlay(rec: VoiceRecordingResponse) {
    // Same memo → toggle pause/play.
    if (activeId.value === rec.id && audioEl) {
      if (isPlaying.value) { audioEl.pause(); isPlaying.value = false }
      else { void audioEl.play().catch(() => { isPlaying.value = false }); isPlaying.value = true }
      return
    }
    // New memo — tear down any prior audio first.
    if (audioEl) { audioEl.pause(); audioEl.src = ''; audioEl = null }
    activeId.value = rec.id
    current.value = 0
    duration.value = rec.duration_seconds || 0
    isPlaying.value = true
    const url = `${API_ORIGIN}/api/v1/media/${rec.media_id}/file`
    const a = new Audio(url)
    a.preload = 'auto'
    bindAudio(a)
    audioEl = a
    a.play().catch((e: unknown) => {
      isPlaying.value = false
      const name = e instanceof Error ? e.name : ''
      if (name && name !== 'AbortError') {
        const msg = errMsg(e)
        alert(`Couldn't start playback: ${msg}`)
      }
    })
  }

  function seek(t: number) {
    if (audioEl) { audioEl.currentTime = t; current.value = t }
  }

  async function remove(rec: VoiceRecordingResponse) {
    if (!confirm('Delete this recording?')) return
    if (activeId.value === rec.id) closePlayback()
    try {
      await recordingsApi.delete(rec.id)
      recordings.value = recordings.value.filter((r) => r.id !== rec.id)
    } catch (e: unknown) {
      const msg = errMsg(e)
      alert(`Delete failed: ${msg}`)
    }
  }

  // Entry switch (or unmount): reload the list + tear down playback/capture so
  // the backend doesn't keep recording into a stale entry.
  watch(entryIdRef, () => {
    closePlayback()
    if (recording.value) {
      recording.value = false
      clearTimer()
      void recordingsApi.stop().catch(() => { /* entry switching */ })
    }
    void loadRecordings()
  })

  onUnmounted(() => {
    clearTimer()
    if (audioEl) { audioEl.pause(); audioEl = null }
    if (recording.value) {
      recording.value = false
      void recordingsApi.stop().catch(() => { /* editor unmounted */ })
    }
  })

  void loadRecordings()

  return {
    recordings, loadRecordings,
    recording, elapsed, uploading, hasEntry, toggleRecord,
    activeId, active, isPlaying, current, duration, togglePlay, seek, closePlayback, remove,
  }
}

/** Provide/inject key so the editor's three recording UI pieces share one instance. */
export const RecordingsKey: InjectionKey<RecordingsApi> = Symbol('recordings')

export function useRecordingsInjected(): RecordingsApi {
  const api = inject(RecordingsKey)
  if (!api) throw new Error('useRecordingsInjected() must be used within a component that provides RecordingsKey')
  return api
}

export function provideRecordings(api: RecordingsApi) {
  provide(RecordingsKey, api)
}

/** Format seconds as m:ss. */
export function fmtTime(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
