<script setup lang="ts">
/**
 * RecurrencePicker — a small control that emits an RFC 5545 RRULE string.
 * Supports the common personal-scheduling patterns (none / daily / weekly on
 * chosen days / weekdays / monthly). Pairs with dateutil.rrulestr() on the
 * backend which expands occurrences on demand.
 */
import { computed } from 'vue'
import { Repeat } from 'lucide-vue-next'

const props = defineProps<{ modelValue: string | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

type Freq = 'none' | 'daily' | 'weekly' | 'weekdays' | 'monthly'
const DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']

const state = computed<{ freq: Freq; days: string[] }>(() => {
  const r = (props.modelValue || '').toUpperCase()
  if (!r) return { freq: 'none', days: [] }
  if (r.includes('FREQ=DAILY')) return { freq: 'daily', days: [] }
  if (r.includes('FREQ=MONTHLY')) return { freq: 'monthly', days: [] }
  if (r.includes('FREQ=WEEKLY')) {
    const m = r.match(/BYDAY=([A-Z,]+)/)
    const days = m ? m[1].split(',') : []
    if (days.length === 5 && ['MO', 'TU', 'WE', 'TH', 'FR'].every(d => days.includes(d))) {
      return { freq: 'weekdays', days: [] }
    }
    return { freq: 'weekly', days }
  }
  return { freq: 'none', days: [] }
})

function set(freq: Freq, days: string[] = []) {
  let rule: string | null = null
  switch (freq) {
    case 'none': rule = null; break
    case 'daily': rule = 'FREQ=DAILY'; break
    case 'weekdays': rule = 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'; break
    case 'monthly': rule = 'FREQ=MONTHLY'; break
    case 'weekly': rule = days.length ? `FREQ=WEEKLY;BYDAY=${days.join(',')}` : 'FREQ=WEEKLY'; break
  }
  emit('update:modelValue', rule)
}

function toggleDay(d: string) {
  const days = state.value.days.includes(d)
    ? state.value.days.filter(x => x !== d)
    : [...state.value.days, d]
  set('weekly', days)
}
function onFreqChange(e: Event) {
  set((e.target as HTMLSelectElement).value as Freq, state.value.days)
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center gap-2">
      <Repeat :size="13" class="text-text-muted shrink-0" />
      <select :value="state.freq" @change="onFreqChange"
        class="flex-1 px-2 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent cursor-pointer">
        <option value="none">Does not repeat</option>
        <option value="daily">Daily</option>
        <option value="weekdays">Weekdays (Mon–Fri)</option>
        <option value="weekly">Weekly</option>
        <option value="monthly">Monthly</option>
      </select>
    </div>
    <div v-if="state.freq === 'weekly'" class="flex items-center gap-1 pl-5">
      <button v-for="d in DAYS" :key="d" type="button" @click="toggleDay(d)"
        class="w-7 h-7 rounded-md text-[10px] font-medium border transition-colors cursor-pointer"
        :class="state.days.includes(d)
          ? 'bg-accent text-white border-accent'
          : 'bg-surface-hover text-text-secondary border-border hover:border-accent/50'">
        {{ d[0] }}
      </button>
    </div>
  </div>
</template>
