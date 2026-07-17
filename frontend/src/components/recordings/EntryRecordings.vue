<script setup lang="ts">
import { FileAudio, Play, Pause, Trash2 } from 'lucide-vue-next'
import { useRecordingsInjected, fmtTime } from '../../composables/useRecordings'

const recs = useRecordingsInjected()

/** A memo is "active" if it's loaded in the player (playing or paused). */
function isActive(id: number): boolean {
  return recs.activeId.value === id
}
</script>

<template>
  <div
    v-if="recs.recordings.value.length"
    class="border-t border-border bg-surface/60 px-3 py-1.5 space-y-0.5"
  >
    <div class="flex items-center gap-1 text-[10px] uppercase tracking-wide text-text-muted mb-0.5">
      <FileAudio :size="10" /> Voice memos
      <span class="normal-case text-text-muted/70">· {{ recs.recordings.value.length }}</span>
    </div>
    <div
      v-for="rec in recs.recordings.value"
      :key="rec.id"
      class="group flex items-center gap-2 px-1.5 py-1 rounded hover:bg-surface-hover transition-colors"
      :class="isActive(rec.id) ? 'bg-accent/10' : ''"
    >
      <button
        class="p-1 rounded-full cursor-pointer transition-colors shrink-0"
        :class="isActive(rec.id) ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-accent hover:bg-accent/10'"
        :title="isActive(rec.id) ? (recs.isPlaying.value ? 'Pause' : 'Resume') : 'Play'"
        @click="recs.togglePlay(rec)"
      >
        <Pause v-if="isActive(rec.id) && recs.isPlaying.value" :size="12" />
        <Play v-else :size="12" />
      </button>
      <FileAudio :size="12" class="text-accent shrink-0" />
      <span class="text-xs text-text-secondary flex-1 truncate">Voice memo</span>
      <span class="text-[10px] font-mono text-text-muted tabular-nums">
        {{ fmtTime(rec.duration_seconds) }}
      </span>
      <button
        class="p-1 rounded text-text-muted hover:text-danger hover:bg-danger/10 cursor-pointer transition-colors opacity-0 group-hover:opacity-100"
        title="Delete recording"
        @click="recs.remove(rec)"
      >
        <Trash2 :size="12" />
      </button>
    </div>
  </div>
</template>
