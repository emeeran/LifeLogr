<script setup lang="ts">
import { AlignLeft, Clock, Check, Loader, Pencil } from 'lucide-vue-next'
import type { SaveState } from '../../composables/useAutoSave'

defineProps<{
  stats: { chars: number; words: number; lines: number; paragraphs: number; readMins: number }
  saveState: SaveState
  hasContent: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-3 px-3 py-0.5 text-[10px] text-text-muted bg-editor/30">
    <span class="flex items-center gap-0.5"><AlignLeft :size="10" /> {{ stats.words }} words</span>
    <span>{{ stats.chars }} chars</span>
    <span class="hidden sm:inline">{{ stats.lines }} lines</span>
    <span class="hidden sm:inline">{{ stats.paragraphs }} paragraphs</span>
    <span class="flex items-center gap-0.5"><Clock :size="10" /> {{ stats.readMins }} min read</span>
    <span class="flex-1" />
    <!-- Save status with clear visual feedback -->
    <span v-if="saveState === 'saving'" class="flex items-center gap-1 text-accent">
      <Loader :size="10" class="animate-spin" /> Saving…
    </span>
    <span v-else-if="saveState === 'pending'" class="flex items-center gap-1 text-amber-500">
      <Pencil :size="10" /> Editing…
    </span>
    <span v-else-if="saveState === 'saved'" class="flex items-center gap-1 text-green-500">
      <Check :size="10" /> Saved
    </span>
    <span v-else-if="hasContent" class="flex items-center gap-1 text-text-muted/70">
      <Check :size="10" /> All changes saved
    </span>
  </div>
</template>
