<script setup lang="ts">
import { computed } from 'vue'
import type { CalendarEntryResponse } from '../../types'
import { History } from 'lucide-vue-next'

const props = defineProps<{
  entries: CalendarEntryResponse[]
  /** Today as YYYY-MM-DD — used to compute "N years ago". */
  today: string
}>()

const emit = defineEmits<{
  openEntry: [entryId: number]
}>()

const groups = computed(() => {
  const byYear = new Map<number, CalendarEntryResponse[]>()
  for (const e of props.entries) {
    const year = Number(e.entry_date.slice(0, 4))
    const list = byYear.get(year)
    if (list) list.push(e)
    else byYear.set(year, [e])
  }
  const thisYear = Number(props.today.slice(0, 4))
  return [...byYear.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, items]) => {
      const ago = thisYear - year
      return {
        year,
        label: `${ago} ${ago === 1 ? 'year' : 'years'} ago`,
        items,
      }
    })
})
</script>

<template>
  <div
    v-if="groups.length"
    class="px-3 py-1.5 flex items-center gap-2 border-b border-border/50 overflow-x-auto"
  >
    <div class="flex items-center gap-1 shrink-0 text-[10px] font-semibold text-text-muted">
      <History :size="12" />
      <span>On this day</span>
    </div>
    <div v-for="g in groups" :key="g.year" class="flex items-center gap-1 shrink-0">
      <span class="text-[10px] text-text-muted">{{ g.label }}</span>
      <button
        v-for="e in g.items"
        :key="e.id"
        class="max-w-[160px] truncate px-1.5 py-0.5 rounded text-[10px] cursor-pointer transition-colors bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-accent/15"
        :title="`${g.label} — ${e.title || (e.is_encrypted ? 'Encrypted' : 'Journal entry')}`"
        @click="emit('openEntry', e.id)"
      >
        {{ e.title || (e.is_encrypted ? 'Encrypted' : 'Journal entry') }}
      </button>
    </div>
  </div>
</template>
