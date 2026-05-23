<script setup lang="ts">
import { onMounted, watch, computed, ref } from 'vue'
import { useCalendar } from '../../composables/useCalendar'
import { useEntriesStore } from '../../stores/entries'
import { useUiStore } from '../../stores/ui'
import { useTagsStore } from '../../stores/tags'
import CalendarHeader from './CalendarHeader.vue'
import CalendarCell from './CalendarCell.vue'
import { Tag, X } from 'lucide-vue-next'

const cal = useCalendar()
const entries = useEntriesStore()
const ui = useUiStore()
const tagsStore = useTagsStore()
const filterTagId = ref<number | null>(null)
const showTagMenu = ref(false)
const selectedDate = ref<string | null>(null)

onMounted(() => tagsStore.fetchTree())

const activeTagName = computed(() => {
  if (filterTagId.value === null) return null
  return tagsStore.tags.find(t => t.id === filterTagId.value)?.name ?? null
})

const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})

const entryMap = computed(() => {
  const map: Record<string, typeof entries.calendarEntries> = {}
  for (const e of entries.calendarEntries) {
    if (filterTagId.value !== null) {
      if (!e.tags.some(t => t.id === filterTagId.value)) continue
    }
    const key = e.entry_date
    ;(map[key] ??= []).push(e)
  }
  return map
})

function loadMonth() {
  entries.fetchCalendarMonth(cal.year.value, cal.month.value)
}

onMounted(loadMonth)
watch(() => [cal.year.value, cal.month.value], loadMonth)
watch(() => entries.lastUpdated, loadMonth)

function selectDate(dateStr: string) {
  selectedDate.value = dateStr
  ui.requestEdit(-1, dateStr)
}

function openEntry(entryId: number) {
  selectedDate.value = null // entry selected, not date
  ui.requestEdit(entryId)
}
</script>

<template>
  <div class="flex flex-col h-full">
    <CalendarHeader
      :label="cal.monthLabel.value"
      @prev="cal.prevMonth"
      @next="cal.nextMonth"
      @today="cal.goToday"
    />

    <!-- Tag filter -->
    <div v-if="tagsStore.tags.length" class="px-3 py-1 flex items-center gap-1.5 border-b border-border/50 relative">
      <button
        class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium cursor-pointer transition-colors"
        :class="filterTagId !== null ? 'bg-accent text-white' : 'bg-surface-hover text-text-secondary hover:text-text-primary'"
        @click="showTagMenu = !showTagMenu"
      >
        <Tag :size="11" />
        <span v-if="activeTagName">#{{ activeTagName }}</span>
        <span v-else>Tags</span>
      </button>
      <button
        v-if="filterTagId !== null"
        class="text-text-muted hover:text-text-primary cursor-pointer"
        @click="filterTagId = null"
        title="Clear filter"
      >
        <X :size="12" />
      </button>

      <!-- Tag dropdown list -->
      <div
        v-if="showTagMenu"
        class="absolute top-full left-3 mt-1 bg-surface border border-border rounded-lg shadow-xl py-1 min-w-[140px] max-h-[200px] overflow-y-auto z-50"
        @click.stop
      >
        <button
          v-for="tag in tagsStore.tags"
          :key="tag.id"
          class="w-full text-left px-3 py-1 text-[11px] cursor-pointer transition-colors"
          :class="filterTagId === tag.id ? 'bg-accent/15 text-accent' : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'"
          @click="filterTagId = tag.id; showTagMenu = false"
        >
          #{{ tag.name }}
        </button>
        <div class="border-t border-border my-0.5" />
        <button
          class="w-full text-left px-3 py-1 text-[11px] text-text-muted hover:bg-surface-hover hover:text-text-primary cursor-pointer"
          @click="filterTagId = null; showTagMenu = false"
        >
          Show all
        </button>
      </div>
    </div>

    <div class="flex-1 p-3 overflow-auto">
      <!-- Day name headers -->
      <div class="grid grid-cols-7 mb-0.5">
        <div
          v-for="d in cal.dayNames"
          :key="d"
          class="text-center text-[11px] font-semibold text-text-muted py-1"
        >
          {{ d }}
        </div>
      </div>

      <!-- Calendar grid -->
      <div class="grid grid-cols-7 gap-px">
        <CalendarCell
          v-for="day in cal.grid.value"
          :key="day.dateStr"
          :date="day.date"
          :date-str="day.dateStr"
          :is-current-month="day.isCurrentMonth"
          :entries="entryMap[day.dateStr] ?? []"
          :is-today="day.dateStr === todayStr"
          :is-selected="day.dateStr === selectedDate"
          @select-date="selectDate"
          @open-entry="openEntry"
        />
      </div>
    </div>
  </div>
</template>
