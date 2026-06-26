<script setup lang="ts">
import { ref } from 'vue'
import type { CalendarEntryResponse } from '../../types'
import EntryPicker from './EntryPicker.vue'

const props = defineProps<{
  date: number
  dateStr: string
  isCurrentMonth: boolean
  entries: CalendarEntryResponse[]
  isToday: boolean
  isSelected: boolean
}>()

const emit = defineEmits<{
  selectDate: [dateStr: string]
  openEntry: [entryId: number]
}>()

const showPicker = ref(false)

function handleClick() {
  if (props.entries.length > 1) {
    showPicker.value = !showPicker.value
  } else if (props.entries.length === 1) {
    emit('openEntry', props.entries[0].id)
  } else {
    emit('selectDate', props.dateStr)
  }
}

function handleOpenEntry(entryId: number) {
  showPicker.value = false
  emit('openEntry', entryId)
}

function handleNewEntry(dateStr: string) {
  showPicker.value = false
  emit('selectDate', dateStr)
}
</script>

<template>
  <div
    class="relative min-h-[60px] border border-border/50 rounded-sm p-1.5 cursor-pointer transition-colors duration-150"
    :class="[
      isCurrentMonth ? (entries.length ? 'bg-accent/5' : 'bg-surface') : (entries.length ? 'bg-accent/5' : 'bg-sidebar/50'),
      isToday ? 'ring-2 ring-accent bg-accent/10' : '',
      isSelected ? 'ring-2 ring-accent/60 bg-accent/10' : '',
      'hover:bg-surface-hover'
    ]"
    @click="handleClick"
  >
    <span
      class="text-[11px] font-semibold"
      :class="[
        isCurrentMonth ? 'text-text-primary' : 'text-text-muted',
        isToday ? 'text-accent' : ''
      ]"
    >
      {{ date }}
    </span>

    <!-- Entry preview -->
    <div
      v-if="entries.length > 0"
      class="mt-0.5 w-full rounded-sm overflow-hidden"
    >
      <p class="text-[10px] text-text-secondary/90 leading-snug line-clamp-2">
        {{ entries[0].title || (entries[0].is_encrypted ? 'Encrypted' : 'Journal entry') }}
      </p>
    </div>

    <!-- Entry count badge -->
    <div
      v-if="entries.length > 1"
      class="absolute bottom-1 right-1 bg-accent text-white text-[9px] font-medium rounded-full w-4 h-4 flex items-center justify-center"
    >
      {{ entries.length }}
    </div>

    <!-- Multi-entry picker -->
    <EntryPicker
      v-if="showPicker"
      :entries="entries"
      :date-str="dateStr"
      @open-entry="handleOpenEntry"
      @new-entry="handleNewEntry"
      @close="showPicker = false"
    />
  </div>
</template>
