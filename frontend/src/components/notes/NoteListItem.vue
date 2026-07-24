<script setup lang="ts">
import { computed } from 'vue'
import { Pin, Lock, Folder } from 'lucide-vue-next'
import type { NoteListItem, NoteFolderResponse } from '../../types'

const props = defineProps<{
  note: NoteListItem
  active: boolean
  folders: NoteFolderResponse[]
}>()
defineEmits<{ select: [] }>()

const folderName = computed(() => {
  if (props.note.folder_id == null) return null
  return props.folders.find((f) => f.id === props.note.folder_id)?.name ?? null
})

const snippet = computed(() => {
  const raw = props.note.body_snippet || ''
  // Strip common markdown markers for a cleaner preview line.
  const stripped = raw
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_`>~\-]/g, '')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
  return stripped.slice(0, 90) || 'No additional text'
})

const displayTitle = computed(() => props.note.title?.trim() || 'Untitled note')

const updatedLabel = computed(() => {
  const d = new Date(props.note.updated_at)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
})
</script>

<template>
  <button
    @click="$emit('select')"
    class="w-full text-left px-3 py-2 rounded-lg transition-colors group"
    :class="active ? 'bg-accent/15 border border-accent/30' : 'hover:bg-surface-hover border border-transparent'"
  >
    <div class="flex items-start gap-2">
      <Pin v-if="note.is_pinned" :size="11" class="text-accent shrink-0 mt-0.5" />
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-1.5">
          <span class="text-xs font-medium text-text-primary truncate flex-1">{{ displayTitle }}</span>
          <Lock v-if="note.is_encrypted" :size="10" class="text-accent shrink-0" />
          <span class="text-[9px] text-text-muted shrink-0">{{ updatedLabel }}</span>
        </div>
        <p class="text-[10px] text-text-muted truncate mt-0.5">{{ snippet }}</p>
        <div v-if="folderName || note.tags.length" class="flex items-center gap-1.5 mt-1 flex-wrap">
          <span
            v-if="folderName"
            class="inline-flex items-center gap-0.5 text-[9px] text-text-secondary bg-surface-hover px-1.5 py-0.5 rounded"
          >
            <Folder :size="9" /> {{ folderName }}
          </span>
          <span
            v-for="t in note.tags"
            :key="t.id"
            class="text-[9px] text-text-secondary bg-surface-hover px-1.5 py-0.5 rounded"
            >#{{ t.name }}</span
          >
        </div>
      </div>
    </div>
  </button>
</template>
