<script setup lang="ts">
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-vue-next'

defineProps<{ label: string }>()
const emit = defineEmits<{ prev: []; next: []; today: []; goto: [] }>()
</script>

<template>
  <div class="flex items-center justify-between px-4 py-3 border-b border-border">
    <h2 class="text-lg font-semibold text-text-primary">{{ label }}</h2>
    <div class="flex items-center gap-1">
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        @click="emit('today')"
      >
        Today
      </button>
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        title="Go to date"
        @click="emit('goto')"
      >
        <Calendar :size="16" />
      </button>
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        @click="emit('prev')"
      >
        <ChevronLeft :size="18" />
      </button>
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        @click="emit('next')"
      >
        <ChevronRight :size="18" />
      </button>
    </div>
  </div>
</template>
