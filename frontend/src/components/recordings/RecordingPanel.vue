<script setup lang="ts">
import { Mic, Square, Loader, FileAudio, Trash2, Sparkles, Play, Pause } from 'lucide-vue-next'
import { ref, onMounted, onUnmounted } from 'vue'
import { recordingsApi } from '../../api/recordings'
import { API_ORIGIN } from '../../api/client'
import type { VoiceRecordingResponse } from '../../types'

const props = defineProps<{ entryId: number }>()
const emit = defineEmits<{ transcribed: [text: string] }>()

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
    const recorder = new MediaRecorder(stream)
    const chunks: Blob[] = []

    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: recorder.mimeType })
      const ext = recorder.mimeType.includes('webm') ? 'webm' : 'ogg'
      const file = new File([blob], `recording-${Date.now()}.${ext}`, { type: recorder.mimeType })
      stream.getTracks().forEach(t => t.stop())
      await uploadRecording(file)
    }

    mediaRecorder.value = recorder
    recorder.start(1000)  // 1s timeslice ensures ondataavailable fires in WebKit2GTK
    recording.value = true
    elapsed.value = 0
    timerInterval = setInterval(() => { elapsed.value++ }, 1000)
  } catch (e: any) {
    if (e.name === 'NotAllowedError') {
      alert('Microphone permission denied. Please allow microphone access in your system settings.')
    } else if (e.name === 'NotFoundError') {
      alert('No microphone found. Please connect a microphone and try again.')
    } else {
      alert(`Recording failed: ${e.message || e}`)
    }
  }
}

function stopRecording() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
  if (mediaRecorder.value?.state === 'recording') {
    mediaRecorder.value.stop()
  }
  recording.value = false
}

async function uploadRecording(file: File) {
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

function togglePlayback(rec: VoiceRecordingResponse) {
  if (playingId.value === rec.id) {
    stopPlayback()
    return
  }
  stopPlayback()
  const url = `${API_ORIGIN}/api/v1/media/${rec.media_id}/file`
  const audio = new Audio(url)
  audio.addEventListener('ended', () => { playingId.value = null })
  audio.addEventListener('error', () => {
    playingId.value = null
    currentAudio = null
    alert(`Playback failed. The audio format (${rec.audio_format}) may not be supported. Try recording again.`)
  })
  currentAudio = audio
  playingId.value = rec.id
  audio.play().catch(() => {
    playingId.value = null
    currentAudio = null
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
        class="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/20 text-accent hover:bg-accent/30 cursor-pointer transition-colors disabled:opacity-50"
        :disabled="uploading"
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
