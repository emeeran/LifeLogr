<script setup lang="ts">
import { ChevronLeft, MoreHorizontal } from 'lucide-vue-next'
import { formatEntryDate } from '../../composables/useFormat'

defineProps<{ dateStr: string }>()
const emit = defineEmits<{ close: []; edit: [] }>()
</script>

<template>
  <div class="flex items-center justify-between px-4 py-3 border-b border-border">
    <div class="flex items-center gap-2">
      <button
        class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer transition-colors"
        @click="emit('close')"
      >
        <ChevronLeft :size="18" />
      </button>
      <h3 class="text-sm font-medium text-text-primary">{{ formatEntryDate(dateStr, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }) }}</h3>
    </div>
    <div class="flex items-center gap-1">
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        @click="emit('edit')"
      >
        <MoreHorizontal :size="18" />
      </button>
    </div>
  </div>
</template>
