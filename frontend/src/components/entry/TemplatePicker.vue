<script setup lang="ts">
import { X } from 'lucide-vue-next'

const emit = defineEmits<{ close: []; select: [template: string] }>()

const templates = [
  { id: 'day-summary', name: 'Day summary', body: '## Day Summary\n\n**Highlights:**\n- \n\n**Lowlights:**\n- \n' },
  { id: 'meal-log', name: 'Meal log', body: '## Meals\n\n**Breakfast:**\n\n**Lunch:**\n\n**Dinner:**\n' },
  { id: 'thought-log', name: 'Thought log', body: '## Thoughts\n\nWhat am I feeling right now?\n\nWhy do I think I feel this way?\n\nWhat can I do about it?\n' },
]
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="emit('close')">
    <div class="bg-surface rounded-lg shadow-xl w-80 border border-border">
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 class="text-sm font-semibold text-text-primary">Templates</h3>
        <button class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" @click="emit('close')">
          <X :size="16" />
        </button>
      </div>
      <div class="p-2">
        <button
          v-for="t in templates"
          :key="t.id"
          class="w-full text-left px-3 py-2 rounded text-sm text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer transition-colors"
          @click="emit('select', t.body)"
        >
          {{ t.name }}
        </button>
      </div>
    </div>
  </div>
</template>
