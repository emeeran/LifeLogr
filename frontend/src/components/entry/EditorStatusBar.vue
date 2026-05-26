<script setup lang="ts">
import { AlignLeft, Clock } from 'lucide-vue-next'

defineProps<{
  stats: { chars: number; words: number; lines: number; paragraphs: number; readMins: number }
  saving: boolean
  saved: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-3 px-3 py-0.5 text-[10px] text-text-muted bg-editor/30">
    <span class="flex items-center gap-0.5"><AlignLeft :size="10" /> {{ stats.words }} words</span>
    <span>{{ stats.chars }} chars</span>
    <span>{{ stats.lines }} lines</span>
    <span>{{ stats.paragraphs }} paragraphs</span>
    <span class="flex items-center gap-0.5"><Clock :size="10" /> {{ stats.readMins }} min read</span>
    <span class="flex-1" />
    <span v-if="saving">Saving...</span>
    <span v-else-if="saved">Saved</span>
  </div>
</template>
