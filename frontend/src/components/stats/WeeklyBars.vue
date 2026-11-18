<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WeeklyCount } from '../../types'

/**
 * Entries-per-week column chart (single series — accent hue, no legend).
 * Lean SVG: ≤24px columns, 4px rounded data-ends (square baseline), hairline
 * gridlines, clean y ticks, per-column hover tooltip, sr-only table twin.
 */
const props = defineProps<{ data: WeeklyCount[] }>()

const W = 560
const H = 180
const PAD_L = 28
const PAD_B = 18
const PAD_T = 8

const maxCount = computed(() => Math.max(1, ...props.data.map((d) => d.count)))
// Clean y ticks: ~3 steps rounded up to a "nice" unit (0 / 5 / 10 …).
const ticks = computed(() => {
  const raw = maxCount.value / 3
  const mag = 10 ** Math.floor(Math.log10(Math.max(1, raw)))
  const step = Math.max(1, Math.ceil(raw / mag) * mag)
  const top = Math.ceil(maxCount.value / step) * step
  const out: number[] = []
  for (let t = 0; t <= top; t += step) out.push(t)
  return out
})

const plotW = W - PAD_L - 4
const plotH = H - PAD_B - PAD_T
const slot = plotW / Math.max(1, props.data.length)
const barW = Math.min(24, slot - 4)

function x(i: number): number {
  return PAD_L + i * slot + (slot - barW) / 2
}
function y(count: number): number {
  return PAD_T + plotH * (1 - count / maxCount.value)
}

/** Rounded top corners (4px), square at the baseline. */
function barPath(i: number, count: number): string {
  const top = y(count)
  const h = PAD_T + plotH - top
  const r = Math.min(4, h)
  const left = x(i)
  const bottom = PAD_T + plotH
  return `M${left},${bottom} L${left},${top + r} Q${left},${top} ${left + r},${top} L${left + barW - r},${top} Q${left + barW},${top} ${left + barW},${top + r} L${left + barW},${bottom} Z`
}

const weekLabel = computed(() => (week: WeeklyCount) => {
  const d = new Date(week.week_start + 'T00:00:00')
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
})

// Hover tooltip (custom div, not a native title — keeps values legible).
const hover = ref<{ i: number; px: number; py: number } | null>(null)
function onEnter(i: number) {
  hover.value = { i, px: x(i) + barW / 2, py: y(props.data[i].count) }
}
function onLeave() {
  hover.value = null
}
</script>

<template>
  <div class="relative">
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      class="w-full"
      role="img"
      aria-label="Entries per week, last 12 weeks"
    >
      <!-- Hairline gridlines + y ticks (recessive, text tokens) -->
      <g>
        <template v-for="t in ticks" :key="t">
          <line
            :x1="PAD_L"
            :x2="W - 4"
            :y1="y(t)"
            :y2="y(t)"
            class="stroke-border"
            stroke-width="1"
          />
          <text
            :x="PAD_L - 4"
            :y="y(t) + 3"
            text-anchor="end"
            class="fill-current text-text-muted"
            font-size="9"
          >
            {{ t }}
          </text>
        </template>
      </g>

      <!-- Columns -->
      <template v-for="(d, i) in data" :key="d.week_start">
        <path v-if="d.count > 0" :d="barPath(i, d.count)" class="fill-accent" />
        <!-- Full-slot hit target (bigger than the mark) -->
        <rect
          :x="PAD_L + i * slot"
          :y="PAD_T"
          :width="slot"
          :height="plotH"
          fill="transparent"
          @mouseenter="onEnter(i)"
          @mouseleave="onLeave"
        />
        <!-- X labels: sparse to avoid collisions -->
        <text
          v-if="i % 2 === data.length % 2"
          :x="PAD_L + i * slot + slot / 2"
          :y="H - 4"
          text-anchor="middle"
          class="fill-current text-text-muted"
          font-size="9"
        >
          {{ weekLabel(d) }}
        </text>
      </template>
    </svg>

    <!-- Hover tooltip -->
    <div
      v-if="hover"
      class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded bg-surface-hover px-1.5 py-0.5 text-[10px] text-text-primary shadow"
      :style="{
        left: `${(hover.px / W) * 100}%`,
        top: `${(hover.py / H) * 100}%`,
      }"
    >
      {{ data[hover.i].count }} {{ data[hover.i].count === 1 ? 'entry' : 'entries' }} ·
      {{ weekLabel(data[hover.i]) }}
    </div>

    <!-- Table twin (screen readers / no-SVG fallback) -->
    <table class="sr-only">
      <caption>Entries per week</caption>
      <thead>
        <tr>
          <th scope="col">Week starting</th>
          <th scope="col">Entries</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in data" :key="d.week_start">
          <td>{{ d.week_start }}</td>
          <td>{{ d.count }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
