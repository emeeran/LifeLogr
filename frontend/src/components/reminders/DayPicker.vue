<script setup lang="ts">
/**
 * DayPicker — accessible day-of-week selector used by reminders.
 *
 * Emits the app's convention ("0=Mon..6=Sun" comma-separated string, matching
 * the backend schema) while presenting friendly single-letter chips with a
 * keyboard-tappable active state. Supports quick presets via a `compact` mode
 * that hides the weekday labels.
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  /** Disable interaction (read-only display). */
  disabled?: boolean
}>(), { disabled: false })

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const DAYS = [
  { key: '0', short: 'M', full: 'Mon' },
  { key: '1', short: 'T', full: 'Tue' },
  { key: '2', short: 'W', full: 'Wed' },
  { key: '3', short: 'T', full: 'Thu' },
  { key: '4', short: 'F', full: 'Fri' },
  { key: '5', short: 'S', full: 'Sat' },
  { key: '6', short: 'S', full: 'Sun' },
]

const active = computed<Set<string>>(() => new Set(props.modelValue.split(',').map(s => s.trim()).filter(Boolean)))

function toggle(key: string) {
  if (props.disabled) return
  const next = new Set(active.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  // Preserve Mon→Sun order regardless of click order.
  const ordered = DAYS.filter(d => next.has(d.key)).map(d => d.key)
  emit('update:modelValue', ordered.join(',') || '0')
}
</script>

<template>
  <div class="inline-flex items-center gap-1" role="group" aria-label="Repeat on days">
    <button v-for="d in DAYS" :key="d.key" type="button"
      :disabled="disabled"
      :title="d.full"
      :aria-pressed="active.has(d.key)"
      @click="toggle(d.key)"
      class="day-chip w-7 h-7 rounded-full text-[11px] font-semibold transition-all cursor-pointer select-none
             flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
      :class="active.has(d.key)
        ? 'bg-accent text-white shadow-sm'
        : 'bg-surface-hover text-text-muted hover:text-text-primary hover:bg-border'">
      {{ d.short }}
    </button>
  </div>
</template>

<style scoped>
.day-chip { border: 1px solid transparent; }
.day-chip[aria-pressed='true'] { border-color: var(--color-accent); }
</style>
