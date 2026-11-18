<script setup lang="ts">
import { computed, watch } from 'vue'
import { useSystemHealthStore } from '../../stores/systemHealth'
import { useUiStore } from '../../stores/ui'

const health = useSystemHealthStore()
const ui = useUiStore()

const errors = computed(() => health.summary.error)
const warns = computed(() => health.summary.warn)
const tone = computed<'error' | 'warn'>(() =>
  errors.value > 0 ? 'error' : 'warn',
)

// Warnings (not errors) self-dismiss after 15 s — they used to linger and
// sit on top of the toolbar, blocking the buttons underneath.
watch(
  () => health.showBanner,
  (shown, _prev, onCleanup) => {
    if (!shown || tone.value !== 'warn') return
    const t = setTimeout(() => health.dismiss(), 15_000)
    onCleanup(() => clearTimeout(t))
  },
  { immediate: true },
)

function view() {
  // Land on the panel that actually lists the findings.
  ui.requestSettingsTab('data', 'maintenance')
}
</script>

<template>
  <Transition name="banner-slide">
    <div
      v-if="health.showBanner"
      role="status"
      class="health-banner flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[12px] shadow-lg cursor-default"
      :class="
        tone === 'error'
          ? 'bg-red-900/90 border-red-700 text-red-200'
          : 'bg-amber-900/90 border-amber-700 text-amber-200'
      "
    >
      <span class="w-2 h-2 rounded-full bg-current shrink-0" />
      <span>
        Health check found
        <strong v-if="errors"
          >{{ errors }} error{{ errors > 1 ? 's' : '' }}</strong
        ><span v-if="errors && warns"> and </span
        ><strong v-if="warns"
          >{{ warns }} warning{{ warns > 1 ? 's' : '' }}</strong
        >.
      </span>
      <button
        class="font-semibold underline cursor-pointer bg-transparent border-0 text-inherit px-1"
        @click="view"
      >
        View
      </button>
      <button
        title="Dismiss"
        class="cursor-pointer bg-transparent border-0 text-inherit text-[15px] leading-none px-0.5"
        @click="health.dismiss()"
      >
        ×
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.health-banner {
  position: fixed;
  /* Below the calendar header / editor title row — at top:10px it physically
     covered the "New entry" toolbar button and swallowed its clicks. */
  top: 60px;
  right: 14px;
  z-index: 80;
  max-width: min(420px, calc(100vw - 28px));
}
.banner-slide-enter-active,
.banner-slide-leave-active {
  transition:
    transform 0.25s ease,
    opacity 0.25s ease;
}
.banner-slide-enter-from,
.banner-slide-leave-to {
  transform: translateY(-12px);
  opacity: 0;
}
</style>
