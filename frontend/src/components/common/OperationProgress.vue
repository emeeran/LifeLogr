<script setup lang="ts">
import { computed } from 'vue'
import type { JobState } from '../../api/jobs'

const props = defineProps<{
  /** Live job state from `useJobProgress`; null renders nothing. */
  job: JobState | null
  /** Human name of the operation, e.g. "Backup" — prefixes the phase line. */
  label?: string
}>()

// Indeterminate when the backend has no total yet (or nothing to count);
// determinate as soon as done/total are both known.
const determinate = computed(
  () => props.job !== null && props.job.percent !== null,
)
const widthPct = computed(() =>
  determinate.value ? `${props.job!.percent}%` : '100%',
)

const phaseText = computed(() => {
  if (!props.job) return ''
  if (props.job.status === 'failed') return props.job.error ?? 'Failed'
  const label = props.label ? `${props.label}: ` : ''
  const phase = props.job.phase
    ? props.job.phase.charAt(0).toUpperCase() + props.job.phase.slice(1)
    : 'Working'
  const detail = props.job.detail ? ` — ${props.job.detail}` : ''
  return `${label}${phase}${detail}`
})

const countText = computed(() => {
  const j = props.job
  if (!j || j.total === null || j.status !== 'running') return ''
  return `${j.done} / ${j.total}`
})
</script>

<template>
  <div v-if="job" class="w-full" data-testid="operation-progress">
    <div class="flex items-center justify-between mb-1 gap-2">
      <span
        class="text-[11px] truncate"
        :class="job.status === 'failed' ? 'text-danger' : 'text-text-secondary'"
      >
        {{ phaseText }}
      </span>
      <span
        v-if="countText"
        class="text-[11px] text-text-muted tabular-nums shrink-0"
      >
        {{ countText }}
      </span>
    </div>
    <div class="h-1.5 rounded-full bg-surface-hover overflow-hidden">
      <!-- Failed paints red at full width; done snaps to a full accent bar. -->
      <div
        class="h-full rounded-full transition-all duration-300"
        :class="[
          job.status === 'failed'
            ? 'bg-danger w-full'
            : job.status === 'done'
              ? 'bg-accent w-full'
              : determinate
                ? 'bg-accent'
                : 'bg-accent/60 animate-pulse',
        ]"
        :style="job.status === 'running' && determinate ? { width: widthPct } : undefined"
      />
    </div>
  </div>
</template>
