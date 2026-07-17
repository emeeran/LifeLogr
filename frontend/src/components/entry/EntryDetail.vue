<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useEntriesStore } from '../../stores/entries'
import { useUiStore } from '../../stores/ui'
import { useTtsStore } from '../../stores/tts'
import { marked } from 'marked'

marked.use({ gfm: true, breaks: true })
import DOMPurify from 'dompurify'
import EntryHeader from './EntryHeader.vue'
import MediaGrid from '../media/MediaGrid.vue'
import { Pencil, Play, Pause, FileAudio, Volume2, Loader } from 'lucide-vue-next'
import { recordingsApi } from '../../api/recordings'
import type { VoiceRecordingResponse } from '../../types'

const entries = useEntriesStore()
const ui = useUiStore()
const tts = useTtsStore()

const entry = computed(() => entries.currentEntry)

const renderedBody = computed(() => {
  if (!entry.value) return ''
  return DOMPurify.sanitize(marked(entry.value.body) as string)
})

// ── Recordings ──
const recordings = ref<VoiceRecordingResponse[]>([])
const playingId = ref<number | null>(null)
let currentAudio: HTMLAudioElement | null = null

onMounted(loadRecordings)
onUnmounted(stopPlayback)

async function loadRecordings() {
  if (!entry.value?.has_recording) return
  try {
    recordings.value = await recordingsApi.listByEntry(entry.value.id)
  } catch { /* ignore */ }
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
  tts.stop()
}

// ── TTS Read Aloud (drives the shared tts store) ──
const ttsEntryId = computed(() => entry.value?.id ?? -1)
const ttsPlaying = computed(() => tts.isPlayingEntry(ttsEntryId.value))
const ttsLoading = computed(() => tts.isLoadingEntry(ttsEntryId.value))

async function toggleTTS() {
  if (!entry.value) return
  // Stop any recording playback before starting read-aloud (separate audio element).
  if (currentAudio) { currentAudio.pause(); currentAudio = null; playingId.value = null }
  try {
    await tts.toggleEntry(entry.value.id)
  } catch (e) {
    console.error('[EntryDetail] read aloud failed:', e)
  }
}

// Pre-warm audio when an entry opens so read-aloud is instant (skip encrypted —
// its body is ciphertext here and can't be synthesized server-side).
watch(ttsEntryId, (id) => {
  if (id > 0 && entry.value && !entry.value.is_encrypted) tts.prewarmEntry(id)
}, { immediate: true })
</script>

<template>
  <div v-if="entry" class="flex flex-col h-full">
    <EntryHeader
      :date-str="entry.entry_date"
      @close="ui.detailPanelOpen = false"
      @edit="ui.startEditing(entry!.id)"
    />

    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- Title -->
      <h2 v-if="entry.title" class="text-lg font-semibold text-text-primary">
        {{ entry.title }}
      </h2>

      <!-- Body (rendered markdown) -->
      <div
        class="md-body max-w-none text-text-primary leading-relaxed"
        :style="{ fontFamily: 'var(--editor-font)', fontSize: 'var(--editor-font-size)' }"
        v-html="renderedBody"
      />

      <!-- Voice recordings -->
      <div v-if="recordings.length" class="space-y-1.5">
        <div
          v-for="rec in recordings"
          :key="rec.id"
          class="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-hover"
        >
          <button
            class="p-1 rounded-full cursor-pointer transition-colors"
            :class="playingId === rec.id ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-accent hover:bg-accent/10'"
            @click="togglePlayback(rec)"
          >
            <Pause v-if="playingId === rec.id" :size="16" />
            <Play v-else :size="16" />
          </button>
          <FileAudio :size="14" class="text-accent shrink-0" />
          <span class="text-xs text-text-secondary flex-1">
            Voice memo
          </span>
        </div>
      </div>

      <!-- Media grid -->
      <MediaGrid v-if="entry.media_count > 0" :entry-id="entry.id" :media-count="entry.media_count" />

      <!-- Tags -->
      <div v-if="entry.tags.length" class="flex flex-wrap gap-1.5 pt-2">
        <span
          v-for="tag in entry.tags"
          :key="tag.id"
          class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-accent/15 text-accent"
        >
          #{{ tag.name }}
        </span>
      </div>
    </div>

    <!-- Bottom bar -->
    <div class="p-3 border-t border-border flex items-center gap-2">
      <button
        class="flex items-center gap-2 px-3 py-2 rounded bg-accent text-white text-sm hover:bg-accent-hover transition-colors cursor-pointer"
        @click="ui.startEditing(entry!.id)"
      >
        <Pencil :size="14" />
        Edit
      </button>
      <button
        class="flex items-center gap-1.5 px-3 py-2 rounded text-sm transition-colors cursor-pointer"
        :class="ttsPlaying ? 'bg-accent/20 text-accent' : 'bg-surface-hover text-text-secondary hover:text-accent'"
        :disabled="ttsLoading || entry.is_encrypted"
        @click="toggleTTS"
        :title="ttsPlaying ? 'Stop reading' : 'Read aloud'"
      >
        <Loader v-if="ttsLoading" :size="14" class="animate-spin" />
        <Pause v-else-if="ttsPlaying" :size="14" />
        <Volume2 v-else :size="14" />
      </button>
    </div>
  </div>
</template>
