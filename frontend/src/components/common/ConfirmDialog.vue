<script setup lang="ts">
import { useHotkey } from '../../composables/useHotkey'

defineProps<{ title: string; message: string }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()

// `modal` scope outranks the editors/global, and Esc must work while the focus
// sits in the dialog's own text fields — hence allowInInput.
useHotkey(
  'escape',
  () => emit('cancel'),
  { scope: 'modal', allowInInput: true },
)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
    @click.self="emit('cancel')"
  >
    <div class="bg-surface rounded-lg shadow-xl w-80 border border-border p-4">
      <h3 class="text-sm font-semibold text-text-primary mb-2">{{ title }}</h3>
      <p class="text-xs text-text-secondary mb-4">{{ message }}</p>
      <div class="flex justify-end gap-2">
        <button
          class="px-3 py-1.5 rounded text-xs text-text-secondary hover:text-text-primary cursor-pointer"
          @click="emit('cancel')"
        >
          Cancel
        </button>
        <button
          class="px-3 py-1.5 rounded bg-danger text-white text-xs cursor-pointer hover:bg-red-600 transition-colors"
          @click="emit('confirm')"
        >
          Confirm
        </button>
      </div>
    </div>
  </div>
</template>
