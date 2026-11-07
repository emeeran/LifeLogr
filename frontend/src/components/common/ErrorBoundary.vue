<script setup lang="ts">
/**
 * ErrorBoundary — keeps a crashing view from taking the whole shell with it.
 *
 * A thrown render/setup error otherwise unmounts the subtree and leaves an
 * empty panel with no message (the "screen goes blank" report). Returning
 * `false` from `onErrorCaptured` stops propagation to the global handler, so
 * this component owns reporting for anything it catches.
 */
import { onErrorCaptured, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Copy, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { errorMessage } from '../../utils/errorMessage'
import { reportClientError } from '../../utils/clientErrors'

const route = useRoute()
const failure = ref<{ message: string; stack: string } | null>(null)
const copied = ref(false)

function report(err: unknown, info: string) {
  const message = errorMessage(err)
  const stack = err instanceof Error ? (err.stack ?? '') : ''
  const view = typeof route.name === 'string' ? route.name : undefined
  failure.value = { message, stack }
  reportClientError({
    message,
    stack,
    component: info || 'view',
    url: window.location.href,
    view,
  })
}

onErrorCaptured((err, _instance, info) => {
  report(err, info)
  return false
})

function reload() {
  window.location.reload()
}

async function copyDetails() {
  if (!failure.value) return
  const details = `${failure.value.message}\n\n${failure.value.stack}\n\nview: ${
    String(route.name ?? '') || 'unknown'
  }`
  try {
    await navigator.clipboard.writeText(details)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* clipboard unavailable — the message is on screen anyway */
  }
}
</script>

<template>
  <div v-if="failure" class="h-full w-full overflow-auto p-6">
    <div
      class="mx-auto max-w-xl rounded-lg border border-border bg-surface p-5 shadow-lg"
    >
      <div class="flex items-start gap-3">
        <TriangleAlert :size="18" class="mt-0.5 shrink-0 text-danger" />
        <div class="min-w-0 flex-1">
          <h2 class="text-sm font-semibold text-text-primary">
            This view stopped rendering
          </h2>
          <p class="mt-1 text-xs text-text-secondary">
            The rest of the app is still running. Reload to recover — your data
            has not been affected.
          </p>
          <pre
            class="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-surface-hover p-2 text-[11px] text-text-muted"
            >{{ failure.message }}</pre
          >
          <div class="mt-3 flex items-center gap-2">
            <button
              class="flex items-center gap-1.5 rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover cursor-pointer"
              @click="reload"
            >
              <RefreshCw :size="12" /> Reload
            </button>
            <button
              class="flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover cursor-pointer"
              @click="copyDetails"
            >
              <Copy :size="12" />
              {{ copied ? 'Copied' : 'Copy details' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
  <slot v-else />
</template>
