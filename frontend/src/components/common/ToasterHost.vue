<script setup lang="ts">
/**
 * ToasterHost — the single place app-wide failures and confirmations reach the
 * user. Mounted once in App.vue; anything (any store, any component) pushes via
 * the toast store and shows up here. Visuals mirror the SettingsView toast.
 */
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-vue-next'
import { useToastStore } from '../../stores/toast'

const toast = useToastStore()
</script>

<template>
  <div
    class="pointer-events-none fixed bottom-4 left-4 z-[400] flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-2"
    role="status"
    aria-live="polite"
  >
    <TransitionGroup name="toast">
      <div
        v-for="t in toast.toasts"
        :key="t.id"
        class="pointer-events-auto flex items-center gap-2 rounded-md border px-3 py-1.5 text-[12px] shadow-lg"
        :class="{
          'bg-green-900/90 border-green-700 text-green-100':
            t.type === 'success',
          'bg-red-900/90 border-red-700 text-red-100': t.type === 'error',
          'bg-surface border-border text-text-primary': t.type === 'info',
        }"
      >
        <CheckCircle2
          v-if="t.type === 'success'"
          :size="14"
          class="shrink-0"
        />
        <AlertTriangle v-else-if="t.type === 'error'" :size="14" class="shrink-0" />
        <Info v-else :size="14" class="shrink-0" />
        <span class="min-w-0 flex-1 break-words">{{ t.message }}</span>
        <button
          class="ml-auto shrink-0 cursor-pointer p-0.5 opacity-70 hover:opacity-100"
          aria-label="Dismiss notification"
          @click="toast.dismiss(t.id)"
        >
          <X :size="12" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
