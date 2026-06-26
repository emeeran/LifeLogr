<script setup lang="ts">
import { computed } from 'vue'
import { Play, Pause, X, FileAudio } from 'lucide-vue-next'
import { useRecordingsInjected, fmtTime } from '../../composables/useRecordings'

const recs = useRecordingsInjected()

const visible = computed(() => recs.activeId.value !== null && recs.active.value !== null)

/** Slider value bound to current time; writes seek back on input. */
function onSeek(e: Event) {
  const v = Number((e.target as HTMLInputElement).value)
  recs.seek(v)
}
</script>

<template>
  <Transition name="player-pop">
    <div
      v-if="visible"
      class="absolute bottom-20 left-1/2 -translate-x-1/2 z-30 w-[min(92%,360px)] flex items-center gap-2.5 px-3 py-2 rounded-xl bg-surface border border-border shadow-2xl"
    >
      <button
        class="flex items-center justify-center h-8 w-8 rounded-full bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors shrink-0"
        :title="recs.isPlaying.value ? 'Pause' : 'Play'"
        @click="recs.active.value && recs.togglePlay(recs.active.value)"
      >
        <Pause v-if="recs.isPlaying.value" :size="14" />
        <Play v-else :size="14" />
      </button>

      <FileAudio :size="14" class="text-accent shrink-0" />

      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between text-[10px] text-text-muted font-mono tabular-nums mb-0.5">
          <span>Voice memo</span>
          <span>{{ fmtTime(recs.current.value) }} / {{ fmtTime(recs.duration.value) }}</span>
        </div>
        <input
          type="range"
          class="w-full h-1 accent-accent cursor-pointer"
          min="0"
          :max="Math.max(1, Math.floor(recs.duration.value || recs.active.value?.duration_seconds || 0))"
          :value="Math.floor(recs.current.value)"
          :disabled="(recs.duration.value || recs.active.value?.duration_seconds || 0) === 0"
          @input="onSeek"
        />
      </div>

      <button
        class="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors shrink-0"
        title="Close player"
        @click="recs.closePlayback()"
      >
        <X :size="14" />
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.player-pop-enter-active,
.player-pop-leave-active {
  transition: all 0.2s ease;
}
.player-pop-enter-from,
.player-pop-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
</style>
