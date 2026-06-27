<script setup lang="ts">
/**
 * SplashScreen — a brief dedication shown while the app loads.
 *
 * Displays the memorial portrait with the "Ever in memory of you" title that
 * flashes once, holds for a moment, then dismisses (auto after a few seconds,
 * or on click / Escape). Shown on startup when the memorial-title feature is on.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { X } from 'lucide-vue-next'
import memorialImg from '../../assets/tariq-memorial-tribute.jpg'

const emit = defineEmits<{ done: [] }>()
const flash = ref(false)
let dismissTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  // Trigger the one-shot title flash on the next frame (after initial paint).
  requestAnimationFrame(() => { flash.value = true })
  // Hold the splash for a beat, then fade out.
  dismissTimer = setTimeout(() => emit('done'), 10000)
  window.addEventListener('keydown', onKey, { once: true })
})
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') emit('done') }
function skip() { emit('done') }
onUnmounted(() => {
  if (dismissTimer) clearTimeout(dismissTimer)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div class="splash fixed inset-0 z-[200] flex flex-col items-center justify-center bg-stone-950 px-6 cursor-pointer"
    title="Click to continue" @click="skip">
    <h1 class="splash-title" :class="{ flash }">Ever in memory of you</h1>
    <img :src="memorialImg"
      alt="In Loving Remembrance — Tariq Al Fayad (1997–2020)"
      class="splash-img mt-4 max-w-full object-contain rounded-md"
      style="filter: drop-shadow(0 16px 50px rgba(0,0,0,0.7));"
      draggable="false" />

    <button type="button"
      class="close-btn absolute bottom-6 inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-[12px] font-medium text-white/85 hover:text-white"
      title="Close (Esc)" @click.stop="skip">
      <X :size="13" /> Close
    </button>
    <p class="absolute bottom-2 left-0 right-0 text-center text-[10px] text-white/35">Click anywhere or press Esc to continue</p>
  </div>
</template>

<style scoped>
.splash-title {
  margin: 0;
  font-family: Georgia, 'Times New Roman', serif;
  font-style: italic; font-weight: 600;
  font-size: clamp(1.3rem, 4vw, 2.2rem);
  letter-spacing: 0.02em;
  color: #f4d6a3;
  text-shadow: 0 0 18px rgba(255,180,80,0.45), 0 1px 6px rgba(0,0,0,0.6);
  opacity: 0;
}
.splash-title.flash { animation: title-flash 2.6s ease-out forwards; }
.splash-img { max-height: 68vh; }

@keyframes title-flash {
  0%   { opacity: 0; filter: blur(10px); letter-spacing: 0.32em; }
  12%  { opacity: 1; filter: blur(0) brightness(2.4); text-shadow: 0 0 40px rgba(255,205,130,0.95), 0 0 8px rgba(255,235,180,0.9); }
  26%  { opacity: 1; filter: brightness(0.85); text-shadow: 0 0 12px rgba(255,180,80,0.4), 0 1px 6px rgba(0,0,0,0.6); }
  42%  { opacity: 1; filter: brightness(2.2); text-shadow: 0 0 36px rgba(255,205,130,0.9); }
  58%  { opacity: 1; filter: brightness(0.9); text-shadow: 0 0 14px rgba(255,180,80,0.45); }
  74%  { opacity: 1; filter: brightness(1.6); text-shadow: 0 0 26px rgba(255,205,130,0.75); }
  100% { opacity: 1; filter: brightness(1); letter-spacing: 0.02em; text-shadow: 0 0 18px rgba(255,180,80,0.45), 0 1px 6px rgba(0,0,0,0.6); }
}
@media (prefers-reduced-motion: reduce) {
  .splash-title { opacity: 1; }
  .splash-title.flash { animation: none; }
}
</style>
