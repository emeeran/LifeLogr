<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CalendarEntryResponse } from '../../types'
import { useEntriesStore } from '../../stores/entries'
import { useUiStore } from '../../stores/ui'
import { useCalendar } from '../../composables/useCalendar'
import { formatDDMMYYYY } from '../../composables/useFormat'
import { useConfirm } from '../../composables/useConfirm'
import { Merge, Pencil, Plus, Trash2 } from 'lucide-vue-next'

const props = defineProps<{
  entries: CalendarEntryResponse[]
  dateStr: string
}>()

const emit = defineEmits<{
  openEntry: [entryId: number]
  newEntry: [dateStr: string]
  close: []
}>()

const entriesStore = useEntriesStore()
const ui = useUiStore()
const cal = useCalendar()
const deletingId = ref<number | null>(null)
const merging = ref(false)
const selectedIds = ref<Set<number>>(new Set())

// Prune selections that no longer exist (e.g. an entry deleted from the
// picker mid-selection) so the merge button never references stale ids.
watch(
  () => props.entries,
  (entries) => {
    const ids = new Set(entries.map((e) => e.id))
    if (selectedIds.value.size && [...selectedIds.value].some((id) => !ids.has(id))) {
      selectedIds.value = new Set([...selectedIds.value].filter((id) => ids.has(id)))
    }
  },
)

// Encrypted entries hold ciphertext server-side, so the backend refuses to
// merge them — hide the checkbox rather than let the request fail later.
const mergeableCount = computed(() => props.entries.filter((e) => !e.is_encrypted).length)
const canMerge = computed(() => selectedIds.value.size >= 2)

function toggleSelect(entry: CalendarEntryResponse) {
  const next = new Set(selectedIds.value)
  if (next.has(entry.id)) next.delete(entry.id)
  else next.add(entry.id)
  selectedIds.value = next
}

async function handleDelete(e: MouseEvent, entry: CalendarEntryResponse) {
  e.stopPropagation()
  if (deletingId.value !== null) return
  const { confirm } = useConfirm()
  if (
    !(await confirm({
      title: 'Delete entry',
      message: `Delete "${entry.title || 'Untitled'}"? It moves to trash and can be restored later.`,
      confirmLabel: 'Delete',
    }))
  )
    return
  deletingId.value = entry.id
  try {
    await entriesStore.deleteEntry(entry.id)
    // If the deleted entry is open in the editor, close it so the editor
    // doesn't keep showing a now-deleted entry. The calendar refresh below
    // already drops it from the grid — this keeps the two in sync.
    if (ui.editingEntryId === entry.id) {
      ui.editorIsDirty = false
      ui.startEditing(null)
    }
    await entriesStore.fetchCalendarMonth(cal.year.value, cal.month.value)
    // If no entries left on this date, close the picker
    const remaining = props.entries.filter((en) => en.id !== entry.id)
    if (remaining.length === 0) {
      emit('close')
    }
  } finally {
    deletingId.value = null
  }
}

async function handleMerge(e: MouseEvent) {
  e.stopPropagation()
  if (!canMerge.value || merging.value) return
  const ids = [...selectedIds.value]
  const { confirm } = useConfirm()
  if (
    !(await confirm({
      title: 'Merge entries',
      message: `Combine ${ids.length} entries into one? Their texts are joined in order and media stays attached; the originals move to trash.`,
      confirmLabel: 'Merge',
    }))
  )
    return
  merging.value = true
  try {
    const merged = await entriesStore.mergeEntries(ids)
    // If a merged source was open in the editor, show the survivor instead.
    if (ids.includes(ui.editingEntryId ?? -1)) {
      ui.editorIsDirty = false
      ui.startEditing(merged.id)
    }
    await entriesStore.fetchCalendarMonth(cal.year.value, cal.month.value)
    selectedIds.value = new Set()
    emit('close')
  } finally {
    merging.value = false
  }
}
</script>

<template>
  <div
    class="absolute z-50 bg-surface border border-border rounded-lg shadow-xl p-2 min-w-[200px] max-w-[260px]"
    style="top: 100%; right: 0"
    @click.stop
  >
    <div class="text-[10px] font-semibold text-text-muted mb-1 px-1">
      {{ formatDDMMYYYY(dateStr) }}
    </div>

    <div
      v-for="entry in entries"
      :key="entry.id"
      class="flex items-start gap-2 w-full text-left px-2 py-1.5 rounded hover:bg-surface-hover cursor-pointer transition-colors group"
      @click="emit('openEntry', entry.id)"
    >
      <input
        v-if="!entry.is_encrypted && mergeableCount > 1"
        type="checkbox"
        class="mt-0.5 accent-[var(--color-accent)] cursor-pointer shrink-0"
        :checked="selectedIds.has(entry.id)"
        title="Select for merge"
        @click.stop="toggleSelect(entry)"
      />
      <Pencil :size="11" class="text-accent mt-0.5 shrink-0" />
      <div class="min-w-0 flex-1">
        <div class="text-xs font-medium text-text-primary truncate">
          {{ entry.title || 'Untitled' }}
        </div>
        <div
          v-if="!entry.is_encrypted"
          class="text-[10px] text-text-secondary truncate"
        >
          {{ entry.title ? '' : 'Journal entry' }}
        </div>
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

    <template v-if="canMerge">
      <div class="border-t border-border my-1" />
      <button
        class="flex items-center gap-2 w-full px-2 py-1.5 rounded hover:bg-accent/10 text-accent cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="merging || deletingId !== null"
        title="Merge selected entries into one"
        @click="handleMerge($event)"
      >
        <Merge :size="11" />
        <span class="text-xs">Merge selected ({{ selectedIds.size }})</span>
      </button>
    </template>

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
