<script setup lang="ts">
import { Mic, Square, Loader } from 'lucide-vue-next'
import { useRecordingsInjected, fmtTime } from '../../composables/useRecordings'

const recs = useRecordingsInjected()
</script>

<template>
  <div class="absolute bottom-20 right-4 z-30 flex items-center gap-2">
    <!-- Recording-in-progress pill: pulsing dot + timer + Stop -->
    <Transition name="rec-pop">
      <div
        v-if="recs.recording.value"
        class="flex items-center gap-2 pl-2.5 pr-1.5 py-1.5 rounded-full bg-surface border border-danger/40 shadow-lg"
      >
        <span class="relative flex h-2.5 w-2.5 shrink-0">
          <span class="absolute inline-flex h-full w-full rounded-full bg-danger opacity-60 animate-ping" />
          <span class="relative inline-flex h-2.5 w-2.5 rounded-full bg-danger" />
        </span>
        <span class="text-xs font-mono text-text-primary tabular-nums">{{ fmtTime(recs.elapsed.value) }}</span>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium bg-danger/20 text-danger hover:bg-danger/30 cursor-pointer transition-colors"
          title="Stop recording"
          @click="recs.toggleRecord()"
        >
          <Square :size="10" /> Stop
        </button>
      </div>
    </Transition>

    <!-- Saving state pill -->
    <Transition name="rec-pop">
      <div
        v-if="recs.uploading.value"
        class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full bg-surface border border-border shadow-lg"
      >
        <Loader :size="12" class="animate-spin text-accent" />
        <span class="text-[11px] text-text-secondary">Saving…</span>
      </div>
    </Transition>

    <!-- Floating action button: starts / stops capture -->
    <button
      class="flex items-center justify-center h-10 w-10 rounded-full shadow-lg cursor-pointer transition-all hover:scale-105"
      :class="recs.recording.value
        ? 'bg-danger text-white'
        : 'bg-accent text-white hover:bg-accent-hover'"
      :title="recs.hasEntry.value ? 'Record voice memo' : 'Save the entry, then record'"
      @click="recs.toggleRecord()"
    >
      <Square v-if="recs.recording.value" :size="16" />
      <Loader v-else-if="recs.uploading.value" :size="16" class="animate-spin" />
      <Mic v-else :size="18" />
    </button>
  </div>
</template>

<style scoped>
.rec-pop-enter-active,
.rec-pop-leave-active {
  transition: all 0.18s ease;
}
.rec-pop-enter-from,
.rec-pop-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
</style>
