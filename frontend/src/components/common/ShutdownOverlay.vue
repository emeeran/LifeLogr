<script setup lang="ts">
/**
 * ShutdownOverlay — shown when the window was closed while a backup (or an
 * import/restore) is still running.
 *
 * The desktop shell refuses to exit until the backend reports idle, so without
 * this the user would see the window close and the process linger with no
 * explanation. "Close anyway" tells the shell to stop waiting; teardown still
 * runs, so the sidecar is never orphaned.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Loader } from 'lucide-vue-next'
import { isTauri } from '../../api/client'

const reasons = ref<string[] | null>(null)
const label = computed(() => (reasons.value ? describe(reasons.value) : ''))
let unlisten: (() => void) | null = null

const LABELS: Record<string, string> = {
  backup: 'backup',
  import: 'import',
  restore: 'restore',
}

function describe(list: string[]): string {
  const named = list.map((r) => LABELS[r] ?? r)
  if (named.length === 0) return 'work in progress'
  if (named.length === 1) return `the ${named[0]}`
  return named.map((r) => `the ${r}`).join(' and ')
}

onMounted(async () => {
  if (!isTauri) return
  try {
    const { listen } = await import('@tauri-apps/api/event')
    unlisten = await listen<{ reasons?: string[] }>('shutdown-pending', (event) => {
      reasons.value = event.payload?.reasons?.length
        ? event.payload.reasons
        : ['work in progress']
    })
  } catch {
    /* non-Tauri build or plugin unavailable — nothing to wait for */
  }
})

onUnmounted(() => unlisten?.())

async function closeAnyway() {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('exit_now', { force: true })
  } catch {
    /* if this fails the shell's own wait limit still closes the app */
  }
}
</script>

<template>
  <div
    v-if="reasons"
    class="fixed inset-0 z-[300] flex items-center justify-center bg-black/60"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="shutdown-title"
  >
    <div class="mx-4 w-full max-w-sm rounded-lg border border-border bg-surface p-5 shadow-xl">
      <div class="flex items-start gap-3">
        <Loader :size="18" class="mt-0.5 shrink-0 animate-spin text-accent" />
        <div class="min-w-0 flex-1">
          <h2 id="shutdown-title" class="text-sm font-semibold text-text-primary">
            Finishing {{ label }}…
          </h2>
          <p class="mt-1 text-xs text-text-secondary">
            LifeLogr will close as soon as it completes, so the archive is not
            cut off mid-write. This usually takes a few seconds.
          </p>
          <button
            class="mt-3 rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover cursor-pointer"
            @click="closeAnyway"
          >
            Close anyway
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
