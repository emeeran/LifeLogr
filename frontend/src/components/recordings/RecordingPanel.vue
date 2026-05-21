<script setup lang="ts">
import { Mic, Square, Loader, FileAudio, Trash2, Sparkles, Play, Pause } from 'lucide-vue-next'
import { ref, onMounted, onUnmounted } from 'vue'
import { recordingsApi } from '../../api/recordings'
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
    alert('Audio recording requires a secure context (HTTPS or localhost). In the installed app, microphone access may not be available.')
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
    recorder.start()
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
  const url = `/api/v1/media/${rec.media_id}/file`
  const audio = new Audio(url)
  audio.addEventListener('ended', () => { playingId.value = null })
  currentAudio = audio
  playingId.value = rec.id
  audio.play()
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
  <div class="space-y-2">
    <!-- Record controls -->
    <div class="flex items-center gap-2">
      <button
        v-if="!recording"
        class="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium bg-accent/20 text-accent hover:bg-accent/30 cursor-pointer transition-colors disabled:opacity-50"
        :disabled="uploading"
        @click="startRecording"
      >
        <Mic :size="13" />
        Record
      </button>
      <button
        v-else
        class="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium bg-danger/20 text-danger hover:bg-danger/30 cursor-pointer transition-colors animate-pulse"
        @click="stopRecording"
      >
        <Square :size="13" />
        Stop
      </button>

      <span v-if="recording" class="text-[11px] text-danger font-mono">{{ fmtTime(elapsed) }}</span>
      <span v-if="uploading" class="flex items-center gap-1 text-[11px] text-text-muted">
        <Loader :size="11" class="animate-spin" /> Uploading...
      </span>
    </div>

    <!-- Recording list -->
    <div v-if="recordings.length" class="space-y-1">
      <div
        v-for="rec in recordings"
        :key="rec.id"
        class="flex items-center gap-1.5 px-2 py-1 rounded bg-surface-hover text-[11px]"
      >
        <!-- Play/Pause -->
        <button
          class="p-0.5 rounded hover:bg-accent/15 cursor-pointer transition-colors"
          :class="playingId === rec.id ? 'text-accent' : 'text-text-secondary hover:text-accent'"
          @click="togglePlayback(rec)"
        >
          <Pause v-if="playingId === rec.id" :size="12" />
          <Play v-else :size="12" />
        </button>
        <FileAudio :size="12" class="text-accent shrink-0" />
        <span class="text-text-secondary flex-1 truncate">
          {{ rec.audio_format.toUpperCase() }}
        </span>
        <!-- Transcribe -->
        <button
          v-if="!rec.is_transcribed"
          class="p-0.5 rounded hover:bg-accent/15 text-text-muted hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
          :disabled="transcribingId === rec.id"
          title="Transcribe"
          @click="transcribe(rec)"
        >
          <Loader v-if="transcribingId === rec.id" :size="11" class="animate-spin" />
          <Sparkles v-else :size="11" />
        </button>
        <span v-else class="text-[9px] text-green-400" title="Transcribed">&#10003;</span>
        <!-- Delete -->
        <button
          class="p-0.5 rounded hover:bg-danger/15 text-text-muted hover:text-danger cursor-pointer transition-colors"
          title="Delete recording"
          @click="deleteRecording(rec)"
        >
          <Trash2 :size="11" />
        </button>
      </div>
      <div v-if="recordings.some(r => r.is_transcribed)" class="text-[10px] text-text-muted">
        Transcription appended to entry body.
      </div>
    </div>
  </div>
</template>
