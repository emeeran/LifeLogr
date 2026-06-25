<script setup lang="ts">
/**
 * UpdateStatus — the single update-check affordance.
 *
 * Previously the same `useUpdateChecker` state was rendered three different
 * ways (About hero, What's New, General). This component is the one shared
 * implementation: a compact row with a "Check for updates" button plus an
 * inline status chip. Emits `available` so the parent can surface a toast.
 */
import { computed } from 'vue'
import { RefreshCw, CheckCircle2, DownloadCloud, WifiOff, ExternalLink } from 'lucide-vue-next'
import { APP_VERSION } from '../../../version'
import { useUpdateChecker } from '../../../composables/useUpdateChecker'
import SButton from './SButton.vue'

const emit = defineEmits<{
  result: [kind: 'available' | 'up-to-date' | 'offline', latest?: string]
}>()

const { status, checkedAt, check } = useUpdateChecker()
const checking = computed(() => status.value.kind === 'checking')

async function handleCheck() {
  await check()
  const s = status.value
  if (s.kind === 'available') emit('result', 'available', s.latest)
  else if (s.kind === 'up-to-date') emit('result', 'up-to-date', APP_VERSION)
  else if (s.kind === 'offline') emit('result', 'offline')
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleDateString() } catch { return iso }
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <SButton variant="outline" :icon="RefreshCw" :disabled="checking" @click="handleCheck">
        <RefreshCw v-if="checking" :size="12" class="animate-spin" />
        {{ checking ? 'Checking…' : 'Check for updates' }}
      </SButton>

      <span v-if="status.kind === 'up-to-date'"
        class="inline-flex items-center gap-1 text-[11px] text-green-600 font-medium">
        <CheckCircle2 :size="13" /> Up to date
      </span>
      <span v-else-if="status.kind === 'offline'"
        class="inline-flex items-center gap-1 text-[11px] text-amber-600 font-medium">
        <WifiOff :size="13" /> Offline
      </span>
      <a v-else-if="status.kind === 'available'" :href="status.url" target="_blank" rel="noopener noreferrer"
        class="sbtn sbtn-primary sbtn-sm animate-pulse">
        <DownloadCloud :size="12" /> {{ status.latest }} <ExternalLink :size="10" />
      </a>
      <span v-else-if="checkedAt" class="text-[10px] text-text-muted">
        Last checked {{ fmtDate(checkedAt.toISOString()) }}
      </span>
    </div>

    <!-- Update-available banner with release notes preview -->
    <div v-if="status.kind === 'available'"
      class="rounded-md border border-accent/30 bg-accent/5 p-2.5 space-y-1.5">
      <div class="flex items-center justify-between gap-2">
        <div class="text-[12px] font-medium text-accent flex items-center gap-1.5">
          <DownloadCloud :size="13" /> LifeLogr {{ status.latest }}
          <span v-if="status.publishedAt" class="text-[10px] text-text-muted font-normal">
            · {{ fmtDate(status.publishedAt) }}
          </span>
        </div>
        <a :href="status.url" target="_blank" rel="noopener noreferrer"
          class="sbtn sbtn-primary sbtn-xs">
          Download <ExternalLink :size="10" />
        </a>
      </div>
      <div v-if="status.notes"
        class="text-[11px] text-text-secondary max-h-40 overflow-y-auto whitespace-pre-line pr-1">
        {{ status.notes.replace(/#[^\n]*\n/g, '').slice(0, 600) }}{{ status.notes.length > 600 ? '…' : '' }}
      </div>
    </div>
  </div>
</template>
