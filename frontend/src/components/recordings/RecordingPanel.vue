<script setup lang="ts">
import { Mic, Square, Loader, FileAudio, Trash2, Play, Pause } from 'lucide-vue-next'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { recordingsApi } from '../../api/recordings'
import { API_ORIGIN } from '../../api/client'
import type { VoiceRecordingResponse } from '../../types'

const props = defineProps<{ entryId: number }>()

/** A real, persisted entry id is required before we can record. */
const hasValidEntry = computed(() => props.entryId != null && props.entryId > 0)

const recording = ref(false)
const elapsed = ref(0)
const recordings = ref<VoiceRecordingResponse[]>([])
const uploading = ref(false)
const playingId = ref<number | null>(null)
let timerInterval: ReturnType<typeof setInterval> | null = null
let currentAudio: HTMLAudioElement | null = null

onMounted(loadRecordings)
onUnmounted(() => {
  clearTimer()
  stopPlayback()
  // If a capture is mid-flight, tell the backend to stop so it doesn't keep
  // recording after the panel closes (fire-and-forget — the panel is gone).
  if (recording.value) {
    recording.value = false
    void recordingsApi.stop().catch(() => { /* panel unmounted */ })
  }
})

function clearTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
}

async function loadRecordings() {
  try {
    recordings.value = await recordingsApi.listByEntry(props.entryId)
  } catch { /* entry may have no recordings yet */ }
}

async function startRecording() {
  if (!hasValidEntry.value) {
    alert('Please save this entry first, then record.')
    return
  }
  // Capture runs in the BACKEND (sounddevice → PulseAudio/ALSA), NOT the
  // webview's MediaRecorder. The webview's MediaRecorder is unreliable in the
  // packaged WebKit2GTK build (0-byte files); capturing server-side behaves
  // identically in the browser (dev) and the desktop app (prod). We just tell
  // the backend to start, then run a local timer for the UI.
  recording.value = true
  elapsed.value = 0
  timerInterval = setInterval(() => { elapsed.value++ }, 1000)
  try {
    await recordingsApi.start(props.entryId)
  } catch (e: any) {
    clearTimer()
    recording.value = false
    alert(`Could not start recording: ${e?.message || e}\n\nCheck that a microphone is connected.`)
  }
}

async function stopRecording() {
  clearTimer()
  const wasRecording = recording.value
  recording.value = false
  if (!wasRecording) return
  // The backend stops the capture and encodes an Ogg/Vorbis audio note; we add it.
  uploading.value = true
  try {
    const rec = await recordingsApi.stop()
    recordings.value.push(rec)
  } catch (e: any) {
    alert(`Recording failed: ${e?.message || e}`)
  } finally {
    uploading.value = false
  }
}

async function deleteRecording(rec: VoiceRecordingResponse) {
  if (!confirm('Delete this recording?')) return
  if (playingId.value === rec.id) stopPlayback()
  try {
    await recordingsApi.delete(rec.id)
    recordings.value = recordings.value.filter(r => r.id !== rec.id)
  } catch (e: any) {
    alert(`Delete failed: ${e.message}`)
  }
}

function mediaErrorMessage(audio: HTMLAudioElement, rec: VoiceRecordingResponse): string {
  // Map the HTMLMediaElement error code to a human-readable cause.
  const err = audio.error
  if (!err) return `Playback failed for "${rec.audio_format.toUpperCase()}".`
  switch (err.code) {
    case 1: return 'Playback aborted.'
    case 2: return 'A network error blocked audio playback. Is the backend running?'
    case 3: return `Unable to decode this audio (${rec.audio_format.toUpperCase()}). The recording may be empty or in a format WebKit can't decode — try recording again.`
    case 4: return `This audio format (${rec.audio_format.toUpperCase()}) isn't supported by the media player.`
    default: return `Playback failed (error ${err.code}).`
  }
}

function togglePlayback(rec: VoiceRecordingResponse) {
  if (playingId.value === rec.id) {
    stopPlayback()
    return
  }
  stopPlayback()
  const url = `${API_ORIGIN}/api/v1/media/${rec.media_id}/file`
  const audio = new Audio(url)
  audio.preload = 'auto'
  audio.addEventListener('ended', () => { playingId.value = null })
  audio.addEventListener('error', () => {
    playingId.value = null
    currentAudio = null
    const err = audio.error
    // Network error (code 2) often means the file is missing on disk (404).
    if (err && err.code === 2) {
      const del = confirm(
        'This recording file is missing from disk (it may have been removed).\n\n' +
        'Remove this broken recording from the list?'
      )
      if (del) deleteRecording(rec)
      return
    }
    const msg = mediaErrorMessage(audio, rec)
    // Offer a recovery path: open the raw file in the browser, which uses a
    // different decoder path and often succeeds where <audio> fails.
    const open = confirm(`${msg}\n\nOpen the audio file directly in your browser?`)
    if (open) window.open(url, '_blank')
  })
  currentAudio = audio
  playingId.value = rec.id
  audio.play().catch((e) => {
    playingId.value = null
    currentAudio = null
    // If play() rejects immediately (e.g. NotAllowedError), surface it.
    if (e?.name && e.name !== 'AbortError') {
      alert(`Couldn't start playback: ${e.message || e.name}`)
    }
  })
}

function stopPlayback() {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio = null
  }
  playingId.value = null
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, '0')}`
}
</script>

<template>
  <div class="p-2 space-y-1">
    <!-- Record controls — single compact row -->
    <div class="flex items-center gap-1.5">
      <button
        v-if="!recording"
        class="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/20 text-accent hover:bg-accent/30 cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="uploading || !hasValidEntry"
        :title="hasValidEntry ? 'Record voice memo' : 'Save the entry first'"
        @click="startRecording"
      >
        <Mic :size="11" /> Record
      </button>
      <button
        v-else
        class="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-danger/20 text-danger hover:bg-danger/30 cursor-pointer transition-colors animate-pulse"
        @click="stopRecording"
      >
        <Square :size="10" /> Stop
      </button>
      <span v-if="recording" class="text-[10px] text-danger font-mono">{{ fmtTime(elapsed) }}</span>
      <span v-if="uploading" class="flex items-center gap-1 text-[10px] text-text-muted">
        <Loader :size="10" class="animate-spin" /> Saving...
      </span>
    </div>

    <!-- Recording list — compact rows -->
    <div v-if="recordings.length" class="space-y-0.5">
      <div
        v-for="rec in recordings"
        :key="rec.id"
        class="flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-hover text-[10px]"
      >
        <button
          class="p-px rounded hover:bg-accent/15 cursor-pointer transition-colors"
          :class="playingId === rec.id ? 'text-accent' : 'text-text-secondary hover:text-accent'"
          @click="togglePlayback(rec)"
        >
          <Pause v-if="playingId === rec.id" :size="10" />
          <Play v-else :size="10" />
        </button>
        <FileAudio :size="10" class="text-accent shrink-0" />
        <span class="text-text-secondary flex-1 truncate">{{ rec.audio_format.toUpperCase() }}</span>
        <button
          class="p-px rounded hover:bg-danger/15 text-text-muted hover:text-danger cursor-pointer transition-colors"
          title="Delete"
          @click="deleteRecording(rec)"
        >
          <Trash2 :size="10" />
        </button>
      </div>
    </div>
  </div>
</template>
