<script setup lang="ts">
/**
 * NowPlayingBar — minimal chrome for the shared read-aloud player (tts store).
 *
 * The store owns a single HTMLAudioElement and exposes currentTime/duration
 * for exactly this bar. It offers stop and seek only: the store has no
 * pause/resume, so none is shown. Sits above any bottom chrome and slides in
 * while a stream is active (loading or playing).
 */
import { computed } from 'vue'
import { Volume2, X } from 'lucide-vue-next'
import { useTtsStore } from '../../stores/tts'
import { useEntriesStore } from '../../stores/entries'

const tts = useTtsStore()
const entries = useEntriesStore()

const visible = computed(() => tts.current !== null)

// The store knows the source kind, not a display title; the journal entry's
// title is only resolvable while that entry is the open one.
const title = computed(() => {
  const c = tts.current
  if (!c) return ''
  if (
    c.kind === 'entry' &&
    entries.currentEntry &&
    entries.currentEntry.id === c.entryId
  )
    return entries.currentEntry.title?.trim() || 'Journal entry'
  return 'Read aloud'
})

const percent = computed(() =>
  tts.duration > 0
    ? Math.min(100, Math.round((tts.currentTime / tts.duration) * 100))
    : 0,
)

function fmt(s: number): string {
  const total = Math.max(0, Math.floor(s))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
</script>

<template>
  <Transition name="np-slide">
    <div
      v-if="visible"
      role="status"
      aria-label="Read aloud"
      class="fixed bottom-3 right-3 z-40 flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-editor/50 border border-border backdrop-blur shadow-lg text-[11px] text-text-secondary"
    >
      <Volume2
        :size="13"
        class="text-accent shrink-0"
        :class="{ 'opacity-60': !tts.isPlaying }"
      />
      <span class="max-w-[11rem] truncate" :title="title">{{ title }}</span>

      <!-- Progress track: click to seek (the store's other transport control). -->
      <div
        role="progressbar"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-label="Playback position"
        class="relative h-1 w-24 rounded-full bg-border/70 overflow-hidden cursor-pointer"
        title="Click to seek"
        @click="
          (e) => {
            const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
            if (tts.duration > 0)
              tts.seek(((e.clientX - r.left) / r.width) * tts.duration)
          }
        "
      >
        <div
          class="absolute inset-y-0 left-0 bg-accent rounded-full"
          :style="{ width: percent + '%' }"
        />
      </div>

      <span class="tabular-nums text-[10px] text-text-muted shrink-0">
        {{ fmt(tts.currentTime) }} /
        {{ tts.duration > 0 ? fmt(tts.duration) : '–' }}
      </span>

      <button
        class="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
        title="Stop read aloud"
        aria-label="Stop read aloud"
        @click="tts.stop()"
      >
        <X :size="12" />
      </button>
    </div>
  </Transition>
</template>

<style scoped>
/* Entrance: a short slide-up, suppressed entirely under reduced motion. */
.np-slide-enter-active,
.np-slide-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
}
.np-slide-enter-from,
.np-slide-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
@media (prefers-reduced-motion: reduce) {
  .np-slide-enter-active,
  .np-slide-leave-active {
    transition: none;
  }
  .np-slide-enter-from,
  .np-slide-leave-to {
    transform: none;
  }
}
</style>
