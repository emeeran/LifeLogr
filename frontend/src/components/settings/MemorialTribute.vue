<script setup lang="ts">
/**
 * MemorialTribute — a minimal, full-page dedication.
 *
 * The tribute image is shown in full on a dark matting (nothing cropped, so
 * the dates and message stay visible), with generous padding around it. A
 * single glass dock holds the participatory elements and is **draggable** —
 * place it anywhere over the memorial; the position persists. The dock fades
 * in on hover / keyboard focus and hides otherwise, leaving the artwork
 * undisturbed.
 *
 *  • Interactive candle — click to light or extinguish (a ritual of
 *    remembrance). When lit, a warm glow washes the scene. Persists.
 *  • Rotating tributes — your own short lines fade-rotate in the dock;
 *    editable via Personalize, persisted locally.
 *  • Respects `prefers-reduced-motion`.
 */
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { Pencil, Check, Plus, X, Move } from 'lucide-vue-next'

defineProps<{ image?: string }>()

// ── Persisted content ──
const tributeLines = useLocalStorage<string[]>('lifelogr-memorial-tributes', [
  'Forever in our hearts.',
  'Gone from our sight, never from our love.',
  'Your light still guides us.',
  'In every page written, you are remembered.',
  'Cherished today, tomorrow, always.',
])
const candleLit = useLocalStorage<boolean>('lifelogr-memorial-candle-lit', true)
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)
// Dock position stored as the dock *centre* in % of the container.
const dockPos = useLocalStorage<{ x: number; y: number }>('lifelogr-memorial-dock-pos', { x: 50, y: 90 })

// ── Personalize sheet ──
const showPersonalize = ref(false)
const flash = ref(false)
const newTribute = ref('')
function addTribute() {
  const t = newTribute.value.trim()
  if (t) { tributeLines.value = [...tributeLines.value, t]; newTribute.value = '' }
}
function removeTribute(i: number) {
  tributeLines.value = tributeLines.value.filter((_, idx) => idx !== i)
}
function moveTribute(i: number, dir: -1 | 1) {
  const arr = [...tributeLines.value]
  const j = i + dir
  if (j < 0 || j >= arr.length) return
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  tributeLines.value = arr
}
function resetTributes() {
  tributeLines.value = [
    'Forever in our hearts.',
    'Gone from our sight, never from our love.',
    'Your light still guides us.',
    'In every page written, you are remembered.',
    'Cherished today, tomorrow, always.',
  ]
}

// ── Rotating tributes (non-empty lines only) ──
const tributes = computed(() => tributeLines.value.map(t => t.trim()).filter(Boolean))
const tributeIndex = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
function stopRotation() { if (timer) { clearInterval(timer); timer = null } }
function startRotation() {
  stopRotation()
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!reduce && tributes.value.length > 1) {
    timer = setInterval(() => {
      tributeIndex.value = (tributeIndex.value + 1) % tributes.value.length
    }, 5000)
  }
}
onMounted(startRotation)
onUnmounted(stopRotation)
watch(tributes, () => {
  if (tributeIndex.value >= tributes.value.length) tributeIndex.value = 0
  startRotation()
})

function toggleCandle() { candleLit.value = !candleLit.value }

// ── Draggable dock ──
const memorialEl = ref<HTMLElement | null>(null)
const dockEl = ref<HTMLElement | null>(null)
const dragging = ref(false)
const dragOffset = { x: 0, y: 0 }   // pointer offset from dock centre (px)

function clampDock() {
  const cont = memorialEl.value, dock = dockEl.value
  if (!cont || !dock) return
  const cw = cont.clientWidth, ch = cont.clientHeight, dw = dock.offsetWidth, dh = dock.offsetHeight
  const halfW = (dw / 2 / cw) * 100, halfH = (dh / 2 / ch) * 100
  const x = Math.max(halfW, Math.min(dockPos.value.x, 100 - halfW))
  const y = Math.max(halfH, Math.min(dockPos.value.y, 100 - halfH))
  if (x !== dockPos.value.x || y !== dockPos.value.y) dockPos.value = { x, y }
}

function onDragStart(e: PointerEvent) {
  const cont = memorialEl.value, dock = dockEl.value
  if (!cont || !dock) return
  e.preventDefault()
  const dRect = dock.getBoundingClientRect()
  const cx = dRect.left + dRect.width / 2
  const cy = dRect.top + dRect.height / 2
  dragOffset.x = e.clientX - cx
  dragOffset.y = e.clientY - cy
  dragging.value = true
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd, { once: true })
}
function onDragMove(e: PointerEvent) {
  const cont = memorialEl.value
  if (!cont || !dragging.value) return
  const cRect = cont.getBoundingClientRect()
  const dock = dockEl.value!
  const halfW = dock.offsetWidth / 2, halfH = dock.offsetHeight / 2
  let cx = e.clientX - dragOffset.x
  let cy = e.clientY - dragOffset.y
  cx = Math.max(cRect.left + halfW, Math.min(cx, cRect.right - halfW))
  cy = Math.max(cRect.top + halfH, Math.min(cy, cRect.bottom - halfH))
  dockPos.value = {
    x: ((cx - cRect.left) / cRect.width) * 100,
    y: ((cy - cRect.top) / cRect.height) * 100,
  }
}
function onDragEnd() {
  dragging.value = false
  window.removeEventListener('pointermove', onDragMove)
}

onMounted(() => {
  nextTick(() => {
    clampDock()
    // Play the title flash once per load (when the title is enabled).
    if (memorialTitle.value) flash.value = true
  })
})
onUnmounted(() => {
  stopRotation()
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
})
</script>

<template>
  <div ref="memorialEl"
    class="memorial relative h-full w-full overflow-hidden bg-stone-950 flex flex-col p-5 sm:p-8 lg:p-10"
    :class="{ lit: candleLit }">

    <!-- Dedication title (flashes once on load) -->
    <div v-if="memorialTitle" class="title-area shrink-0 text-center pb-2 sm:pb-3">
      <h2 class="memorial-title" :class="{ flash }">Ever in memory of you</h2>
    </div>

    <!-- Tribute image (contained, full artwork visible — nothing cropped) -->
    <div class="image-area flex-1 min-h-0 flex items-center justify-center">
      <img v-if="image" :src="image"
        alt="In Loving Remembrance — Tariq Al Fayad (1997–2020)"
        class="art max-w-full max-h-full object-contain rounded-md"
        style="filter: drop-shadow(0 12px 40px rgba(0,0,0,0.6));"
        draggable="false" />
    </div>

    <!-- Warm candlelight wash -->
    <div class="warm-glow" :class="{ on: candleLit }" aria-hidden="true" />

    <!-- Draggable, auto-hiding dock -->
    <div ref="dockEl"
      class="dock absolute z-10 w-max max-w-[92%]"
      :class="{ 'force-show': showPersonalize || dragging }"
      :style="{ left: dockPos.x + '%', top: dockPos.y + '%' }">
      <div class="glass rounded-2xl flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2.5"
        :class="dragging ? 'cursor-grabbing' : ''">
        <!-- Drag handle -->
        <button type="button"
          class="dock-handle shrink-0 flex items-center justify-center w-5 h-8 rounded text-white/40 hover:text-white/80 cursor-grab"
          :class="{ 'text-white/80': dragging }"
          title="Drag to move" @pointerdown="onDragStart">
          <Move :size="13" />
        </button>
        <span class="w-px h-6 bg-white/15 shrink-0" />

        <!-- Interactive candle -->
        <button type="button" class="candle-wrap shrink-0" :aria-pressed="candleLit"
          :title="candleLit ? 'Extinguish candle' : 'Light a candle'" @click="toggleCandle">
          <div class="candle">
            <template v-if="candleLit">
              <div class="flame"><div class="flame-inner" /></div>
              <div class="glow" />
            </template>
            <div class="wick" />
            <div class="wax" />
          </div>
          <span class="candle-hint">{{ candleLit ? 'Extinguish' : 'Light' }}</span>
        </button>

        <!-- Rotating tribute -->
        <div class="flex-1 min-w-0 text-center px-1">
          <Transition name="tribute-fade" mode="out-in">
            <p v-if="tributes.length" :key="tributeIndex"
              class="tribute italic font-medium text-white/95 leading-snug">
              &ldquo;{{ tributes[tributeIndex] }}&rdquo;
            </p>
            <p v-else key="empty" class="tribute italic text-white/60">Add a personal tribute…</p>
          </Transition>
        </div>

        <!-- Personalize -->
        <button type="button"
          class="dock-btn shrink-0"
          :class="showPersonalize ? 'bg-white text-stone-900' : 'bg-white/15 text-white/85 hover:bg-white/25'"
          :title="showPersonalize ? 'Done' : 'Personalize tributes'"
          @click="showPersonalize = !showPersonalize">
          <component :is="showPersonalize ? Check : Pencil" :size="12" />
        </button>
      </div>
    </div>

    <!-- ── Personalize sheet (tribute lines) ── -->
    <Transition name="sheet">
      <div v-if="showPersonalize" class="sheet personalize-sheet absolute z-20">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-1.5">
            <Pencil :size="12" class="text-amber-200" />
            <h4 class="text-[12px] font-semibold text-white">Tribute lines</h4>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" @click="resetTributes" class="text-[10px] text-white/50 hover:text-rose-300 cursor-pointer">Reset</button>
            <button type="button" @click="showPersonalize = false" class="p-0.5 rounded text-white/60 hover:text-white hover:bg-white/10 cursor-pointer"><X :size="14" /></button>
          </div>
        </div>
        <p class="text-[11px] text-white/70 mb-2">These rotate in the dock. They stay private on your device.</p>
        <div class="space-y-1.5 max-h-[40vh] overflow-y-auto pr-1">
          <div v-for="(line, i) in tributeLines" :key="i" class="flex items-center gap-1.5">
            <input :value="line" @input="tributeLines[i] = ($event.target as HTMLInputElement).value"
              class="edit-input flex-1" />
            <button type="button" @click="moveTribute(i, -1)" :disabled="i === 0"
              class="p-1 rounded text-white/60 hover:text-white hover:bg-white/10 disabled:opacity-30 cursor-pointer" title="Move up">▲</button>
            <button type="button" @click="moveTribute(i, 1)" :disabled="i === tributeLines.length - 1"
              class="p-1 rounded text-white/60 hover:text-white hover:bg-white/10 disabled:opacity-30 cursor-pointer" title="Move down">▼</button>
            <button type="button" @click="removeTribute(i)"
              class="p-1 rounded text-white/60 hover:text-rose-300 hover:bg-rose-400/15 cursor-pointer" title="Remove"><X :size="12" /></button>
          </div>
        </div>
        <div class="mt-2 flex items-center gap-1.5">
          <input v-model="newTribute" class="edit-input flex-1" placeholder="Add a tribute line…"
            @keydown.enter.prevent="addTribute" />
          <button type="button" @click="addTribute" :disabled="!newTribute.trim()"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium bg-amber-400 text-stone-900 hover:bg-amber-300 disabled:opacity-40 cursor-pointer transition-colors">
            <Plus :size="11" /> Add
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ── Glass ── */
.glass {
  background: rgba(20, 16, 12, 0.55);
  backdrop-filter: blur(14px) saturate(1.1);
  -webkit-backdrop-filter: blur(14px) saturate(1.1);
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 8px 32px -8px rgba(0, 0, 0, 0.6);
}

/* ── Image (subtle life) ── */
.art { animation: breathe 20s ease-in-out infinite alternate; }
@keyframes breathe { 0% { transform: scale(1.0); } 100% { transform: scale(1.025); } }

/* ── Warm candlelight wash ── */
.warm-glow {
  position: absolute; inset: 0; pointer-events: none; opacity: 0; transition: opacity 1s ease;
  background: radial-gradient(70% 60% at 50% 100%, rgba(255,170,70,0.16) 0%, transparent 65%);
}
.warm-glow.on { opacity: 1; }

/* ── Dedication title (flashes once on load) ── */
.memorial-title {
  margin: 0;
  font-family: Georgia, 'Times New Roman', serif;
  font-style: italic;
  font-weight: 600;
  font-size: clamp(1.05rem, 3vw, 1.55rem);
  letter-spacing: 0.02em;
  color: #f4d6a3;
  text-shadow: 0 0 18px rgba(255,180,80,0.45), 0 1px 6px rgba(0,0,0,0.6);
  opacity: 0;
}
.memorial-title.flash { animation: title-flash 2.6s ease-out forwards; }
@keyframes title-flash {
  0%   { opacity: 0; filter: blur(10px); letter-spacing: 0.32em; }
  12%  { opacity: 1; filter: blur(0) brightness(2.4); text-shadow: 0 0 40px rgba(255,205,130,0.95), 0 0 8px rgba(255,235,180,0.9); }
  26%  { opacity: 1; filter: brightness(0.85); text-shadow: 0 0 12px rgba(255,180,80,0.4), 0 1px 6px rgba(0,0,0,0.6); }
  42%  { opacity: 1; filter: brightness(2.2); text-shadow: 0 0 36px rgba(255,205,130,0.9); }
  58%  { opacity: 1; filter: brightness(0.9); text-shadow: 0 0 14px rgba(255,180,80,0.45); }
  74%  { opacity: 1; filter: brightness(1.6); text-shadow: 0 0 26px rgba(255,205,130,0.75); }
  100% { opacity: 1; filter: brightness(1); letter-spacing: 0.02em; text-shadow: 0 0 18px rgba(255,180,80,0.45), 0 1px 6px rgba(0,0,0,0.6); }
}

/* ── Auto-hiding, draggable dock ── */
.dock {
  transform: translate(-50%, -50%);
  opacity: 0; pointer-events: none;
  transition: opacity 0.35s ease;
}
.memorial:hover .dock,
.memorial:focus-within .dock,
.dock.force-show { opacity: 1; pointer-events: auto; }
.dock-handle { touch-action: none; }

.dock-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2rem; height: 2rem; border-radius: 9999px; cursor: pointer; transition: background-color 0.15s ease, color 0.15s ease;
}

/* ── Candle ── */
.candle-wrap { background: none; border: none; padding: 0; display: flex; flex-direction: column; align-items: center; cursor: pointer; }
.candle-hint { margin-top: 0.35rem; font-size: 8px; letter-spacing: 0.06em; text-transform: uppercase; color: rgba(255,255,255,0.55); white-space: nowrap; }
.candle { position: relative; width: 24px; height: 46px; display: flex; flex-direction: column; align-items: center; }
.candle .wax {
  width: 20px; height: 40px; margin-top: auto;
  background: linear-gradient(180deg, #f3ede0 0%, #e6dcc4 100%);
  border-radius: 4px 4px 6px 6px;
  box-shadow: inset -3px 0 6px rgba(0,0,0,0.15), inset 3px 0 4px rgba(255,255,255,0.4);
}
.candle .wick { width: 2px; height: 6px; background: #2b2b2b; border-radius: 1px; margin-bottom: -2px; z-index: 2; }
.candle .flame {
  position: absolute; top: -18px; left: 50%; transform: translateX(-50%);
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
  position: absolute; top: -30px; left: 50%; transform: translateX(-50%);
  width: 48px; height: 48px; border-radius: 50%;
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

/* ── Rotating tribute ── */
.tribute { font-size: clamp(0.8rem, 2.2vw, 1.02rem); }
.tribute-fade-enter-active, .tribute-fade-leave-active { transition: opacity 0.6s ease, transform 0.6s ease; }
.tribute-fade-enter-from { opacity: 0; transform: translateY(5px); }
.tribute-fade-leave-to   { opacity: 0; transform: translateY(-5px); }

/* ── Personalize sheet ── */
.sheet {
  background: rgba(18, 14, 10, 0.78);
  backdrop-filter: blur(16px) saturate(1.1);
  -webkit-backdrop-filter: blur(16px) saturate(1.1);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 16px;
  padding: 1rem;
  box-shadow: 0 12px 48px -10px rgba(0, 0, 0, 0.6);
  color: #fff;
  left: 50%; top: 1.25rem; transform: translateX(-50%);
  width: min(92%, 30rem);
}
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.28s ease, transform 0.28s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; transform: translate(-50%, 12px); }
.sheet-enter-to, .sheet-leave-from { opacity: 1; transform: translateX(-50%); }

/* ── Edit inputs (on glass) ── */
.edit-input {
  width: 100%; padding: 0.35rem 0.55rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 6px;
  font-size: 12px; color: #fff; outline: none;
  transition: border-color 0.15s ease;
}
.edit-input:focus { border-color: rgba(255, 255, 255, 0.45); }
.edit-input::placeholder { color: rgba(255, 255, 255, 0.4); }

/* ── Respect reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .art { animation: none; }
  .memorial-title { opacity: 1; }
  .memorial-title.flash { animation: none; }
  .candle .flame, .candle .flame-inner, .candle .glow { animation: none; }
}
</style>
