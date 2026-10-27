<script setup lang="ts">
import { AlignLeft, Check, Loader, Pencil, AlertCircle, Target } from 'lucide-vue-next'
import type { SaveState } from '../../composables/useAutoSave'

/**
 * EditorStatusBar — spec §9 ED7: word count, daily-goal progress (journal)
 * and save state. Character / line / paragraph / read-time counts are
 * deliberately not shown.
 */
defineProps<{
  words: number
  saveState: SaveState
  hasContent: boolean
  /** Today's running total vs the daily goal — the chip only shows when a
   *  goal is set (goal > 0); it turns green once the goal is met. */
  daily?: {
    words: number
    goal: number
  }
}>()
</script>

<template>
  <div
    class="flex items-center gap-3 px-3 py-0.5 text-[10px] text-text-muted bg-editor/30"
  >
    <span class="flex items-center gap-0.5"
      ><AlignLeft :size="10" /> {{ words }} words</span
    >
    <span
      v-if="daily && daily.goal > 0"
      class="flex items-center gap-0.5 font-medium"
      :class="daily.words >= daily.goal ? 'text-green-500' : ''"
      :title="`Goal: ${daily.goal} words today`"
    >
      <Target :size="10" />
      today: {{ daily.words }} / {{ daily.goal }}
      <Check v-if="daily.words >= daily.goal" :size="10" />
    </span>
    <span class="flex-1" />
    <!-- Save status with clear visual feedback -->
    <span
      v-if="saveState === 'saving'"
      class="flex items-center gap-1 text-accent"
    >
      <Loader :size="10" class="animate-spin" /> Saving…
    </span>
    <span
      v-else-if="saveState === 'pending'"
      class="flex items-center gap-1 text-amber-500"
    >
      <Pencil :size="10" /> Editing…
    </span>
    <span
      v-else-if="saveState === 'saved'"
      class="flex items-center gap-1 text-green-500"
    >
      <Check :size="10" /> Saved
    </span>
    <span
      v-else-if="saveState === 'error'"
      class="flex items-center gap-1 text-red-400"
    >
      <AlertCircle :size="10" /> Save failed — retry
    </span>
    <span
      v-else-if="hasContent"
      class="flex items-center gap-1 text-text-muted/70"
    >
      <Check :size="10" /> All changes saved
    </span>
  </div>
</template>
