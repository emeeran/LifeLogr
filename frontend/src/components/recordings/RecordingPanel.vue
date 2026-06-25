<script setup lang="ts">
import { Mic, Square, Loader, FileAudio, Trash2, Sparkles, Play, Pause } from 'lucide-vue-next'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { recordingsApi } from '../../api/recordings'
import { API_ORIGIN } from '../../api/client'
import type { VoiceRecordingResponse } from '../../types'

const props = defineProps<{ entryId: number }>()
const emit = defineEmits<{ transcribed: [text: string] }>()

/** A real, persisted entry id is required before we can record/upload. */
const hasValidEntry = computed(() => props.entryId != null && props.entryId > 0)

const recording = ref(false)
const elapsed = ref(0)
const mediaRecorder = ref<MediaRecorder | null>(null)
const recordings = ref<VoiceRecordingResponse[]>([])
const uploading = ref(false)
const transcribingId = ref<number | null>(null)
const playingId = ref<number | null>(null)
let timerInterval: ReturnType<typeof setInterval> | null = null
let currentAudio: HTMLAudioElement | null = null

onMounted(loadRecordings)
onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  stopRecording()
  stopPlayback()
})

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
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert('Audio recording is not available in this environment.\n\nOn Linux (Tauri desktop app), this requires:\n' +
      '1. gstreamer1.0-plugins-bad: sudo apt install gstreamer1.0-plugins-bad\n' +
      '2. Run System Setup from Settings > Features\n\n' +
      'After installing, restart the app.')
    return
  }
  if (typeof MediaRecorder === 'undefined') {
    alert('MediaRecorder is not supported in this browser engine. On Linux, ensure GStreamer plugins are installed:\n\nsudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-bad')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream)
    } catch (mrErr: any) {
      stream.getTracks().forEach(t => t.stop())
      alert(
        `MediaRecorder could not start: ${mrErr?.message || mrErr}\n\n` +
        'This usually means the WebKit/GStreamer audio encoder is unavailable.\n' +
        'On Linux run System Setup (Settings → Features) or:\n' +
        '  sudo apt install gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav'
      )
      return
    }
    const chunks: Blob[] = []

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data)
    }
    recorder.onerror = (ev: Event) => {
      const err = (ev as ErrorEvent).error || (recorder as any).state
      alert(
        `Recording error: ${err?.message || 'capture stopped unexpectedly'}.\n` +
        'This is often a GStreamer encoder issue — try System Setup (Settings → Features).'
      )
      recording.value = false
      if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
      stream.getTracks().forEach(t => t.stop())
    }
    recorder.onstop = async () => {
      const { ext, mime } = audioFormatFor(recorder.mimeType)
      const blob = new Blob(chunks, { type: mime })
      stream.getTracks().forEach(t => t.stop())
      // Guard against 0-byte recordings (the cause of "Playback failed /
      // NotSupportedError"): if no audio data was captured, don't upload an
      // empty file — tell the user and let them retry.
      if (blob.size === 0) {
        alert(
          'No audio was captured (0 bytes). The microphone may not be working\n' +
          'or the encoder produced no data. Please try again, and speak loudly.\n' +
          'If it persists, run System Setup (Settings → Features).'
        )
        return
      }
      const file = new File([blob], `recording-${Date.now()}.${ext}`, { type: mime })
      await uploadRecording(file)
    }

    mediaRecorder.value = recorder
    // Start WITHOUT a timeslice; WebKit2GTK flushes all encoded data on stop
    // via requestData, which is more reliable than timed chunks (timed slices
    // can arrive empty if the encoder hasn't produced a frame yet).
    recorder.start()
    recording.value = true
    elapsed.value = 0
    timerInterval = setInterval(() => { elapsed.value++ }, 1000)
  } catch (e: any) {
    if (e?.name === 'NotAllowedError') {
      alert(
        'Microphone permission denied.\n\n' +
        'On Linux, allow microphone access for LifeLogr in your system privacy settings,\n' +
        'then restart the app. (Desktop build auto-grants this, but your OS/portal may block it.)'
      )
    } else if (e?.name === 'NotFoundError' || e?.name === 'DevicesNotFoundError') {
      alert('No microphone found. Please connect a microphone and try again.')
    } else if (e?.name === 'NotReadableError') {
      alert(
        'Microphone is busy or unreadable. Another app may be using it.\n' +
        'Close other recording apps and try again.'
      )
    } else {
      alert(`Recording failed [${e?.name || 'Error'}]: ${e?.message || e}\n\nPlease report this error.`)
    }
  }
}

function stopRecording() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
  const rec = mediaRecorder.value
  if (rec && rec.state === 'recording') {
    // Flush any buffered audio frames BEFORE stop so ondataavailable fires
    // with real data before onstop runs (prevents 0-byte recordings).
    try { rec.requestData() } catch { /* ignore — stop() will flush anyway */ }
    rec.stop()
  }
  recording.value = false
}

async function uploadRecording(file: File) {
  if (!hasValidEntry.value) {
    alert('Cannot upload recording: this entry is not saved yet.')
    return
  }
  uploading.value = true
  try {
    const rec = await recordingsApi.upload(props.entryId, file)
    recordings.value.push(rec)
  } catch (e: any) {
    alert(`Upload failed: ${e.message}`)
  } finally {
    uploading.value = false
  }
}

async function transcribe(rec: VoiceRecordingResponse) {
  transcribingId.value = rec.id
  try {
    const updated = await recordingsApi.transcribe(rec.id)
    const idx = recordings.value.findIndex(r => r.id === rec.id)
    if (idx >= 0) recordings.value[idx] = updated
    if (updated.transcription) {
      emit('transcribed', updated.transcription)
    }
  } catch (e: any) {
    alert(`Transcription failed: ${e.message}`)
  } finally {
    transcribingId.value = null
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

/**
 * Map a MediaRecorder mimeType to a { ext, mime } pair so the saved file's
 * extension matches its actual encoded bytes.
 *
 * WebKit2GTK (Linux/Tauri) commonly reports `audio/x-wav` or `audio/webm`
 * depending on the installed GStreamer encoders. The previous code defaulted
 * any non-webm type to `.ogg`, which produced WAV bytes named `.ogg` — and
 * the backend then served them as `audio/ogg`, so playback failed.
 */
function audioFormatFor(mimeType: string): { ext: string; mime: string } {
  const mt = (mimeType || '').toLowerCase()
  if (mt.includes('webm')) return { ext: 'webm', mime: 'audio/webm' }
  if (mt.includes('wav'))  return { ext: 'wav',  mime: 'audio/wav' }
  if (mt.includes('ogg'))  return { ext: 'ogg',  mime: 'audio/ogg' }
  if (mt.includes('mp4') || mt.includes('m4a')) return { ext: 'm4a', mime: 'audio/mp4' }
  if (mt.includes('mpeg') || mt.includes('mp3')) return { ext: 'mp3', mime: 'audio/mpeg' }
  if (mt.includes('opus')) return { ext: 'opus', mime: 'audio/ogg' }
  // WebKit2GTK default when no codec info is exposed — wav is the safest
  // portable guess (PCM, universally decodable) and matches GStreamer's
  // common `audio/x-wav` output.
  return { ext: 'wav', mime: mt || 'audio/wav' }
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
        <Loader :size="10" class="animate-spin" /> Uploading...
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
          v-if="!rec.is_transcribed"
          class="p-px rounded hover:bg-accent/15 text-text-muted hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
          :disabled="transcribingId === rec.id"
          title="Transcribe"
          @click="transcribe(rec)"
        >
          <Loader v-if="transcribingId === rec.id" :size="10" class="animate-spin" />
          <Sparkles v-else :size="10" />
        </button>
        <span v-else class="text-[8px] text-green-400" title="Transcribed">&#10003;</span>
        <button
          class="p-px rounded hover:bg-danger/15 text-text-muted hover:text-danger cursor-pointer transition-colors"
          title="Delete"
          @click="deleteRecording(rec)"
        >
          <Trash2 :size="10" />
        </button>
      </div>
      <div v-if="recordings.some(r => r.is_transcribed)" class="text-[9px] text-text-muted px-1">
        Transcription appended to entry body.
      </div>
    </div>
  </div>
</template>
