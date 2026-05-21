<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { X } from 'lucide-vue-next'
import { useTemplatesStore } from '../../stores/templates'
import type { TemplateResponse } from '../../types'

const props = defineProps<{
  template?: TemplateResponse | null
}>()

const emit = defineEmits<{
  saved: []
  close: []
}>()

const store = useTemplatesStore()
const name = ref('')
const body = ref('')

onMounted(() => {
  if (props.template) {
    name.value = props.template.name
    body.value = props.template.body
  }
})

async function handleSave() {
  if (!name.value.trim() || !body.value.trim()) return
  if (props.template) {
    await store.update(props.template.id, { name: name.value, body: body.value })
  } else {
    await store.create({ name: name.value, body: body.value })
  }
  emit('saved')
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-[200] flex items-center justify-center bg-black/40" @click.self="emit('close')">
    <div class="bg-surface border border-border rounded-lg w-[480px] max-h-[80vh] flex flex-col shadow-xl">
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <span class="text-sm font-semibold text-text-primary">
          {{ template ? 'Edit Template' : 'New Template' }}
        </span>
        <button class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" @click="emit('close')">
          <X :size="14" />
        </button>
      </div>

      <!-- Form -->
      <div class="flex-1 overflow-y-auto p-4 space-y-3">
        <div>
          <label class="block text-xs font-medium text-text-secondary mb-1">Name</label>
          <input
            v-model="name"
            class="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
            placeholder="e.g. Morning Pages"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-text-secondary mb-1">Template content (Markdown)</label>
          <textarea
            v-model="body"
            class="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm text-text-primary outline-none focus:border-accent min-h-[200px] resize-y"
            placeholder="## Heading&#10;&#10;Your template content here..."
          />
        </div>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-2 px-4 py-3 border-t border-border">
        <button
          class="px-3 py-1.5 rounded text-xs text-text-secondary hover:bg-surface-hover cursor-pointer"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button
          class="px-3 py-1.5 rounded text-xs bg-accent text-white hover:bg-accent/90 cursor-pointer disabled:opacity-50"
          :disabled="!name.trim() || !body.trim()"
          @click="handleSave"
        >
          {{ template ? 'Update' : 'Create' }}
        </button>
      </div>
    </div>
  </div>
</template>
