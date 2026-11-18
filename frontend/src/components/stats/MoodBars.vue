<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * Mood distribution — an ordered scale (awful→great), so an ordinal one-hue
 * ramp (validated per mode; see --chart-mood-* in main.css), rendered as
 * horizontal bars: square baseline, 4px rounded data-end, value at the tip in
 * text tokens. Moods outside the known scale are appended, gray.
 */
const props = defineProps<{ moods: { mood: string; count: number }[] }>()

const ORDER = ['awful', 'bad', 'meh', 'good', 'great']
const rows = computed(() => {
  const byName = new Map(props.moods.map((m) => [m.mood, m.count]))
  const known = ORDER.filter((m) => byName.has(m)).map((m) => ({
    mood: m,
    count: byName.get(m)!,
    step: ORDER.indexOf(m),
    custom: false,
  }))
  const extra = props.moods
    .filter((m) => !ORDER.includes(m.mood))
    .sort((a, b) => b.count - a.count)
    .map((m) => ({ ...m, step: -1, custom: true }))
  return [...known, ...extra]
})

const maxCount = computed(() => Math.max(1, ...rows.value.map((r) => r.count)))

function fillFor(row: { step: number; custom: boolean }): string {
  if (row.custom) return 'var(--color-text-muted)'
  return `var(--chart-mood-${row.step + 1})`
}

const hover = ref<string | null>(null)
</script>

<template>
  <div>
    <div class="space-y-1.5">
      <div
        v-for="r in rows"
        :key="r.mood"
        class="flex items-center gap-2"
        @mouseenter="hover = r.mood"
        @mouseleave="hover = null"
      >
        <span class="w-12 shrink-0 text-right text-[11px] text-text-secondary">{{
          r.mood
        }}</span>
        <div class="relative h-3.5 flex-1">
          <!-- Track (hairline baseline) + bar (≤24px thick, rounded data-end) -->
          <div
            class="absolute inset-y-0 left-0 rounded-r-[4px] transition-all"
            :style="{
              width: `${(r.count / maxCount) * 100}%`,
              background: fillFor(r),
              outline: hover === r.mood ? '1px solid var(--color-text-muted)' : 'none',
            }"
          />
        </div>
        <span class="w-8 shrink-0 text-[11px] text-text-muted tabular-nums">{{
          r.count
        }}</span>
      </div>
    </div>

    <!-- Table twin (screen readers / no-render fallback) -->
    <table class="sr-only">
      <caption>Mood distribution</caption>
      <thead>
        <tr>
          <th scope="col">Mood</th>
          <th scope="col">Entries</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.mood">
          <td>{{ r.mood }}</td>
          <td>{{ r.count }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
