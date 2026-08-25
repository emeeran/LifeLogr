<script setup lang="ts">
import { onMounted, computed } from 'vue'
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
  Search,
} from 'lucide-vue-next'
import { useSystemHealthStore } from '../../../stores/systemHealth'

const emit = defineEmits<{
  (e: 'toast', type: 'success' | 'error' | 'info', message: string): void
}>()

const health = useSystemHealthStore()
const checks = computed(() => health.report?.checks ?? [])
const ranAt = computed(() =>
  health.report?.ran_at ? new Date(health.report.ran_at).toLocaleString() : '—',
)

onMounted(() => {
  if (!health.loaded) health.load()
})

async function recheck() {
  await health.refresh()
  emit(
    'toast',
    health.hasIssues ? 'error' : 'success',
    health.hasIssues
      ? `Still ${health.issueCount} issue(s).`
      : 'All checks passed.',
  )
}

async function rebuildIndex() {
  await health.rebuildIndex()
  emit('toast', 'success', 'Search index rebuilt.')
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-text-primary">Diagnostics</h3>
        <p class="text-xs text-text-muted">
          Startup app-integrity check — last run {{ ranAt }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border text-[12px] text-text-primary hover:bg-surface-hover cursor-pointer disabled:opacity-50"
          :disabled="health.refreshing"
          @click="rebuildIndex"
        >
          <Search :size="13" />
          Rebuild index
        </button>
        <button
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border text-[12px] text-text-primary hover:bg-surface-hover cursor-pointer disabled:opacity-50"
          :disabled="health.refreshing"
          @click="recheck"
        >
          <RefreshCw
            :size="13"
            :class="{ 'animate-spin': health.refreshing }"
          />
          Re-check
        </button>
      </div>
    </div>

    <div class="flex flex-wrap gap-2 text-[11px]">
      <span
        class="px-2 py-0.5 rounded text-[11px] font-medium bg-green-500/15 text-green-700 dark:bg-green-500/20 dark:text-green-300 border border-green-500/30"
        >OK {{ health.summary.ok }}</span
      >
      <span
        class="px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/15 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300 border border-amber-500/30"
        >Warn {{ health.summary.warn }}</span
      >
      <span
        class="px-2 py-0.5 rounded text-[11px] font-medium bg-red-500/15 text-red-700 dark:bg-red-500/20 dark:text-red-300 border border-red-500/30"
        >Error {{ health.summary.error }}</span
      >
    </div>

    <ul class="space-y-1.5">
      <li
        v-for="c in checks"
        :key="c.id"
        class="flex gap-2 p-2 rounded-md border border-border bg-surface/40"
      >
        <component
          :is="
            c.status === 'ok'
              ? CheckCircle2
              : c.status === 'warn'
                ? AlertTriangle
                : AlertCircle
          "
          :size="15"
          :class="
            c.status === 'ok'
              ? 'text-green-500 dark:text-green-400'
              : c.status === 'warn'
                ? 'text-amber-500 dark:text-amber-400'
                : 'text-red-500 dark:text-red-400'
          "
          class="shrink-0 mt-0.5"
        />
        <div class="min-w-0">
          <div class="text-xs font-medium text-text-primary">{{ c.label }}</div>
          <div class="text-xs text-text-secondary break-words">
            {{ c.detail }}
          </div>
          <div
            v-if="c.hint"
            class="text-xs font-medium text-amber-600 dark:text-amber-400"
          >
            → {{ c.hint }}
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
