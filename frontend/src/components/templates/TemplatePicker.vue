<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { X, Lock, Pencil, Trash2, Plus } from 'lucide-vue-next'
import { useTemplatesStore } from '../../stores/templates'
import type { TemplateResponse } from '../../types'
import TemplateModal from './TemplateModal.vue'

const emit = defineEmits<{
  select: [template: TemplateResponse]
  close: []
}>()

const store = useTemplatesStore()
const showCreateModal = ref(false)
const editingTemplate = ref<TemplateResponse | null>(null)

onMounted(() => {
  if (!store.templates.length) store.fetchAll()
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (editingTemplate.value) { editingTemplate.value = null; return }
  if (showCreateModal.value) { showCreateModal.value = false; return }
  emit('close')
}

function handleSelect(t: TemplateResponse) {
  emit('select', t)
  emit('close')
}

async function handleDelete(t: TemplateResponse) {
  if (!confirm(`Delete template "${t.name}"?`)) return
  await store.remove(t.id)
}

function startEdit(t: TemplateResponse) {
  editingTemplate.value = t
}

function onModalSaved() {
  showCreateModal.value = false
  editingTemplate.value = null
}
</script>

<template>
  <div class="fixed inset-0 z-[200] flex items-center justify-center bg-black/40" @click.self="emit('close')">
    <div class="bg-surface border border-border rounded-lg w-[420px] max-h-[70vh] flex flex-col shadow-xl">
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <span class="text-sm font-semibold text-text-primary">Templates</span>
        <div class="flex items-center gap-1">
          <button
            class="flex items-center gap-1 px-2 py-1 rounded text-xs bg-accent text-white hover:bg-accent/90 cursor-pointer"
            @click="showCreateModal = true"
          >
            <Plus :size="12" /> New
          </button>
          <button class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" @click="emit('close')">
            <X :size="14" />
          </button>
        </div>
      </div>

      <!-- List -->
      <div class="flex-1 overflow-y-auto p-2 space-y-0.5">
        <div
          v-for="t in store.templates"
          :key="t.id"
          class="flex items-center gap-2 px-3 py-2 rounded hover:bg-surface-hover cursor-pointer group transition-colors"
          @click="handleSelect(t)"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5">
              <Lock v-if="t.is_builtin" :size="11" class="text-text-muted shrink-0" />
              <span class="text-sm text-text-primary truncate">{{ t.name }}</span>
            </div>
            <div class="text-[10px] text-text-muted truncate">{{ t.body.slice(0, 80).replace(/\n/g, ' ') }}</div>
          </div>
          <div v-if="!t.is_builtin" class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              class="p-1 rounded hover:bg-accent/15 text-text-secondary hover:text-accent cursor-pointer"
              title="Edit"
              @click.stop="startEdit(t)"
            >
              <Pencil :size="12" />
            </button>
            <button
              class="p-1 rounded hover:bg-danger/15 text-text-secondary hover:text-danger cursor-pointer"
              title="Delete"
              @click.stop="handleDelete(t)"
            >
              <Trash2 :size="12" />
            </button>
          </div>
        </div>

        <div v-if="!store.templates.length" class="text-center py-8 text-xs text-text-muted">
          No templates yet. Click "New" to create one.
        </div>
      </div>
    </div>

    <!-- Create / Edit modal -->
    <TemplateModal
      v-if="showCreateModal"
      @saved="onModalSaved"
      @close="showCreateModal = false"
    />
    <TemplateModal
      v-if="editingTemplate"
      :template="editingTemplate"
      @saved="onModalSaved"
      @close="editingTemplate = null"
    />
  </div>
</template>
