<script setup lang="ts">
import { ref } from 'vue'
import type { EntryResponse } from '../../types'
import { useEntriesStore } from '../../stores/entries'
import { useCalendar } from '../../composables/useCalendar'
import { Pencil, Plus, Trash2 } from 'lucide-vue-next'

const props = defineProps<{
  entries: EntryResponse[]
  dateStr: string
}>()

const emit = defineEmits<{
  openEntry: [entryId: number]
  newEntry: [dateStr: string]
  close: []
}>()

const entriesStore = useEntriesStore()
const cal = useCalendar()
const deletingId = ref<number | null>(null)

function preview(body: string): string {
  return body.slice(0, 60) + (body.length > 60 ? '...' : '')
}

async function handleDelete(e: MouseEvent, entry: EntryResponse) {
  e.stopPropagation()
  if (deletingId.value !== null) return
  if (!confirm(`Delete "${entry.title || 'Untitled'}"?`)) return
  deletingId.value = entry.id
  try {
    await entriesStore.deleteEntry(entry.id)
    await entriesStore.fetchCalendarMonth(cal.year.value, cal.month.value)
    // If no entries left on this date, close the picker
    const remaining = props.entries.filter(e => e.id !== entry.id)
    if (remaining.length === 0) {
      emit('close')
    }
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div
    class="absolute z-50 bg-surface border border-border rounded-lg shadow-xl p-2 min-w-[200px] max-w-[260px]"
    style="top: 100%; right: 0;"
    @click.stop
  >
    <div class="text-[10px] font-semibold text-text-muted mb-1 px-1">{{ dateStr }}</div>

    <div
      v-for="entry in entries"
      :key="entry.id"
      class="flex items-start gap-2 w-full text-left px-2 py-1.5 rounded hover:bg-surface-hover cursor-pointer transition-colors group"
      @click="emit('openEntry', entry.id)"
    >
      <Pencil :size="11" class="text-accent mt-0.5 shrink-0" />
      <div class="min-w-0 flex-1">
        <div class="text-xs font-medium text-text-primary truncate">{{ entry.title || 'Untitled' }}</div>
        <div v-if="!entry.is_encrypted" class="text-[10px] text-text-secondary truncate">{{ preview(entry.body) }}</div>
        <div v-else class="text-[10px] text-text-muted">Encrypted</div>
      </div>
      <button
        class="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-danger/15 text-text-muted hover:text-danger shrink-0 transition-all cursor-pointer"
        :class="{ 'opacity-100': deletingId === entry.id }"
        title="Delete entry"
        :disabled="deletingId !== null"
        @click="handleDelete($event, entry)"
      >
        <Trash2 :size="11" />
      </button>
    </div>

    <div class="border-t border-border my-1" />

    <button
      class="flex items-center gap-2 w-full px-2 py-1.5 rounded hover:bg-accent/10 text-accent cursor-pointer transition-colors"
      @click="emit('newEntry', dateStr)"
    >
      <Plus :size="11" />
      <span class="text-xs">New entry</span>
    </button>
  </div>
</template>
