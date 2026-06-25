<script setup lang="ts">
/**
 * MemorialTribute — an elegant, dynamic "In Loving Memory" panel.
 *
 * Designed to be the emotional focal point of the About tab. It is:
 *
 *  • Dynamic  — a CSS-animated flickering candle (the universal symbol of
 *    remembrance) with a warm glow, a slow Ken-Burns drift on the memorial
 *    photo, gently rising embers, and tribute messages that fade-rotate so
 *    the panel feels alive rather than static.
 *  • Resizable — a Compact / Default / Expanded control lets the user choose
 *    how prominent the memorial is; the choice persists across sessions via
 *    localStorage. Respects accessibility: `prefers-reduced-motion` disables
 *    the candle flicker and Ken-Burns drift.
 *  • Reusable  — all copy is props with sensible defaults, so the same
 *    component can power a first-run tribute or a dedicated memorial view.
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { Heart, Flame } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  name?: string
  years?: string
  /** Rotating short tributes shown beneath the name. */
  tributes?: string[]
  /** Primary dedication line. */
  message?: string
  image?: string
}>(), {
  name: 'Tariq Al Fayad',
  years: '1997 — 2020',
  message: 'LifeLogr is lovingly dedicated to the memory of my son, Tariq — a reminder to cherish every day, and to write it down.',
  image: undefined,
  tributes: () => [
    'Forever in our hearts.',
    'Gone from our sight, never from our love.',
    'Your light still guides us.',
    'In every page written, you are remembered.',
    'Cherished today, tomorrow, always.',
  ],
})

// ── Resizable: three prominence presets persisted to localStorage ──
type SizeKey = 'compact' | 'default' | 'expanded'
const sizeKey = useLocalStorage<SizeKey>('lifelogr-memorial-size', 'default')
const SIZES: Record<SizeKey, { label: string; scale: number }> = {
  compact:  { label: 'Compact',  scale: 0.78 },
  default:  { label: 'Default',  scale: 1.0 },
  expanded: { label: 'Expanded', scale: 1.25 },
}
const scale = computed(() => SIZES[sizeKey.value].scale)

// ── Rotating tributes ──
const tributeIndex = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  // Respect reduced motion: no auto-rotation of messages.
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!reduce && props.tributes.length > 1) {
    timer = setInterval(() => {
      tributeIndex.value = (tributeIndex.value + 1) % props.tributes.length
    }, 5000)
  }
})
onUnmounted(() => { if (timer) clearInterval(timer) })

// ── Embers: deterministic positions so they don't jump on re-render ──
const embers = Array.from({ length: 14 }, (_, i) => ({
  left: 8 + ((i * 37) % 84),        // % horizontal spread
  delay: (i * 1.3) % 8,             // s stagger
  duration: 7 + ((i * 5) % 6),      // s rise time
  size: 2 + ((i * 3) % 3),          // px
}))
</script>

<template>
  <section class="memorial relative overflow-hidden rounded-lg border border-amber-500/30"
    :style="{ '--scale': scale }">

    <!-- Memorial photo backdrop with slow Ken-Burns drift -->
    <div class="absolute inset-0 overflow-hidden">
      <img v-if="image" :src="image" :alt="`In Loving Remembrance — ${name}`"
        class="kb w-full h-full object-cover" />
    </div>
    <div class="absolute inset-0 bg-gradient-to-br from-black/92 via-black/78 to-black/55" />

    <!-- Rising embers -->
    <div class="absolute inset-0 overflow-hidden pointer-events-none">
      <span v-for="(e, i) in embers" :key="i" class="ember"
        :style="{ left: e.left + '%', animationDelay: e.delay + 's', animationDuration: e.duration + 's', width: e.size + 'px', height: e.size + 'px' }" />
    </div>

    <!-- Warm candle glow halo behind the content -->
    <div class="candle-glow absolute pointer-events-none" aria-hidden="true" />

    <div class="relative memorial-body flex items-center gap-5 sm:gap-7 px-6 sm:px-8">
      <!-- Candle (the remembrance flame) -->
      <div class="shrink-0 candle-wrap" aria-hidden="true">
        <div class="candle">
          <div class="flame">
            <div class="flame-inner" />
          </div>
          <div class="glow" />
          <div class="wick" />
          <div class="wax" />
        </div>
      </div>

      <!-- Framed portrait -->
      <div class="shrink-0 portrait-wrap hidden sm:block">
        <div class="portrait ring-2 ring-white/40 shadow-lg overflow-hidden">
          <img v-if="image" :src="image" :alt="name" class="w-full h-full object-cover" />
        </div>
      </div>

      <!-- Text content -->
      <div class="flex-1 min-w-0 text-white">
        <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/10 backdrop-blur-sm border border-white/20">
          <Heart :size="10" class="text-rose-300 fill-rose-300" />
          <span class="text-[9.5px] font-medium uppercase tracking-wider text-white/80">In Loving Memory</span>
        </div>
        <h3 class="mt-2 name text-lg font-semibold leading-tight">{{ name }}</h3>
        <p class="years text-[11px] text-white/70 mt-0.5 italic">{{ years }}</p>

        <!-- Rotating tribute (fade transition) -->
        <Transition name="tribute-fade" mode="out-in">
          <p :key="tributeIndex" class="tribute text-white/85 font-medium italic">
            “{{ tributes[tributeIndex] }}”
          </p>
        </Transition>

        <p class="message text-white/80 mt-2 max-w-md leading-relaxed">{{ message }}</p>
      </div>
    </div>

    <!-- Resize control -->
    <div class="relative flex items-center justify-center gap-1 pb-3 pt-1">
      <span class="flex items-center gap-1 text-[9px] uppercase tracking-wider text-white/50 mr-1.5">
        <Flame :size="9" /> Memorial size
      </span>
      <button v-for="(s, key) in SIZES" :key="key" type="button"
        @click="sizeKey = key as SizeKey"
        class="px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors cursor-pointer"
        :class="sizeKey === key
          ? 'bg-white text-black'
          : 'bg-white/10 text-white/60 hover:bg-white/20 hover:text-white'">
        {{ s.label }}
      </button>
    </div>
  </section>
</template>

<style scoped>
/* ── Scale driven by the resize control ── */
.memorial-body { padding-top: calc(1.75rem * var(--scale)); padding-bottom: calc(0.75rem * var(--scale)); }
.name      { font-size: calc(1.125rem * var(--scale)); }
.years     { font-size: calc(0.7rem * var(--scale)); }
.tribute   { font-size: calc(0.8rem * var(--scale)); margin-top: calc(0.5rem * var(--scale)); }
.message   { font-size: calc(0.75rem * var(--scale)); }
.candle-wrap { transform: scale(var(--scale)); transform-origin: bottom center; }
.portrait  { width: calc(5rem * var(--scale)); height: calc(5rem * var(--scale)); border-radius: 9999px; }
.candle-glow {
  width: calc(220px * var(--scale)); height: calc(220px * var(--scale));
  left: 28px; top: -40px;
  background: radial-gradient(circle, rgba(255,170,70,0.18) 0%, transparent 65%);
}

/* ── Candle ── */
.candle {
  position: relative; width: 26px; height: 54px;
  display: flex; flex-direction: column; align-items: center;
}
.candle .wax {
  width: 22px; height: 46px; margin-top: auto;
  background: linear-gradient(180deg, #f3ede0 0%, #e6dcc4 100%);
  border-radius: 4px 4px 6px 6px;
  box-shadow: inset -3px 0 6px rgba(0,0,0,0.15), inset 3px 0 4px rgba(255,255,255,0.4);
}
.candle .wick { width: 2px; height: 6px; background: #2b2b2b; border-radius: 1px; margin-bottom: -2px; z-index: 2; }
.candle .flame {
  position: absolute; top: -20px; left: 50%; transform: translateX(-50%);
  width: 12px; height: 20px;
  background: radial-gradient(ellipse at 50% 80%, #fff3b0 0%, #ffcf4d 35%, #ff8a1e 65%, #ff5a1e 100%);
  border-radius: 50% 50% 30% 30%;
  transform-origin: bottom center;
  animation: flicker 1.6s ease-in-out infinite alternate;
  box-shadow: 0 0 14px 6px rgba(255,150,50,0.55);
  z-index: 3;
}
.candle .flame-inner {
  position: absolute; bottom: 3px; left: 50%; transform: translateX(-50%);
  width: 5px; height: 9px; background: #7fdcff; border-radius: 50%; opacity: 0.75;
  animation: flicker 1.3s ease-in-out infinite alternate-reverse;
}
.candle .glow {
  position: absolute; top: -32px; left: 50%; transform: translateX(-50%);
  width: 50px; height: 50px; border-radius: 50%;
  background: radial-gradient(circle, rgba(255,180,80,0.5) 0%, transparent 70%);
  animation: glow-pulse 2.2s ease-in-out infinite alternate;
  z-index: 1;
}
@keyframes flicker {
  0%   { transform: translateX(-50%) scale(1) rotate(-1deg); opacity: 0.95; }
  25%  { transform: translateX(-50%) scale(1.04) rotate(1deg); }
  50%  { transform: translateX(-50%) scale(0.97) rotate(-1.5deg); opacity: 1; }
  75%  { transform: translateX(-50%) scale(1.03) rotate(0.5deg); }
  100% { transform: translateX(-50%) scale(1.01) rotate(1deg); opacity: 0.93; }
}
@keyframes glow-pulse {
  from { opacity: 0.7; transform: translateX(-50%) scale(0.95); }
  to   { opacity: 1;   transform: translateX(-50%) scale(1.12); }
}

/* ── Ken Burns drift on the backdrop ── */
.kb { animation: kenburns 26s ease-in-out infinite alternate; transform: scale(1.12); }
@keyframes kenburns {
  0%   { transform: scale(1.12) translate(0, 0); }
  100% { transform: scale(1.22) translate(-2%, -2%); }
}

/* ── Rising embers ── */
.ember {
  position: absolute; bottom: -8px; border-radius: 9999px;
  background: radial-gradient(circle, rgba(255,190,90,0.9) 0%, rgba(255,120,40,0) 70%);
  animation-name: rise; animation-timing-function: ease-in; animation-iteration-count: infinite;
  opacity: 0;
}
@keyframes rise {
  0%   { transform: translateY(0) scale(1); opacity: 0; }
  10%  { opacity: 0.9; }
  90%  { opacity: 0.5; }
  100% { transform: translateY(-220px) scale(0.4) translateX(14px); opacity: 0; }
}

/* ── Tribute rotation fade ── */
.tribute-fade-enter-active, .tribute-fade-leave-active { transition: opacity 0.6s ease, transform 0.6s ease; }
.tribute-fade-enter-from { opacity: 0; transform: translateY(4px); }
.tribute-fade-leave-to   { opacity: 0; transform: translateY(-4px); }

/* ── Respect reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .candle .flame, .candle .flame-inner, .candle .glow { animation: none; }
  .kb { animation: none; transform: scale(1.12); }
  .ember { display: none; }
}
</style>
