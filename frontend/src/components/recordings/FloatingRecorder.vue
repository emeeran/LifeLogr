<script setup lang="ts">
import { Mic, Square, Loader } from 'lucide-vue-next'
import { ref, watch, onUnmounted } from 'vue'
import { useRecordingsInjected, fmtTime } from '../../composables/useRecordings'

const recs = useRecordingsInjected()

// ── Cosmetic amplitude meter ──────────────────────────────────────────────
// Capture stays in the BACKEND (PortAudio → Ogg/Vorbis). This only opens a
// *metering-only* mic stream to drive a live waveform so the user sees the mic
// is hot. On some Linux/PulseAudio setups the backend holding the mic blocks a
// second getUserMedia open in the webview — in that case we fall back to a
// faux animated waveform so there's still clear recording feedback.
const canvas = ref<HTMLCanvasElement | null>(null)
let raf = 0
let analyser: AnalyserNode | null = null
let meterCtx: AudioContext | null = null
let meterStream: MediaStream | null = null
let fauxPhase = 0

function renderBars(ctx: CanvasRenderingContext2D, cv: HTMLCanvasElement, values: number[], max: number) {
  const w = cv.width
  const h = cv.height
  ctx.clearRect(0, 0, w, h)
  const n = values.length
  const gap = 1
  const bw = (w - gap * (n - 1)) / n
  for (let i = 0; i < n; i++) {
    const v = Math.max(0.04, Math.min(1, values[i] / max))
    const bh = Math.max(2, v * h)
    ctx.fillStyle = '#EF4444'
    ctx.globalAlpha = 0.45 + 0.55 * v
    ctx.fillRect(i * (bw + gap), (h - bh) / 2, bw, bh)
  }
  ctx.globalAlpha = 1
}

async function startMeter() {
  const cv = canvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  if (!ctx) return

  // Try a metering-only mic stream for real levels.
  try {
    meterStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    meterCtx = new AudioContext()
    const src = meterCtx.createMediaStreamSource(meterStream)
    analyser = meterCtx.createAnalyser()
    analyser.fftSize = 64
    src.connect(analyser)
    const data = new Uint8Array(analyser.frequencyBinCount)
    const draw = () => {
      raf = requestAnimationFrame(draw)
      analyser!.getByteFrequencyData(data)
      renderBars(ctx, cv, Array.from(data), 255)
    }
    draw()
    return
  } catch {
    // Mic busy/denied (expected on some Linux setups while the backend records).
  }

  // Faux fallback — smooth pseudo-random bars driven by phase, not silence.
  const draw = () => {
    raf = requestAnimationFrame(draw)
    fauxPhase += 0.16
    const bars = Array.from({ length: 16 }, (_, i) =>
      110 + 90 * Math.abs(Math.sin(fauxPhase + i * 0.55)) * (0.55 + 0.45 * Math.sin(fauxPhase * 0.35 + i)),
    )
    renderBars(ctx, cv, bars, 255)
  }
  draw()
}

function stopMeter() {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
  analyser = null
  if (meterStream) {
    meterStream.getTracks().forEach((t) => t.stop())
    meterStream = null
  }
  if (meterCtx) {
    meterCtx.close().catch(() => {})
    meterCtx = null
  }
}

watch(() => recs.recording.value, (rec) => {
  if (rec) void startMeter()
  else stopMeter()
})
onUnmounted(stopMeter)
</script>

<template>
  <div class="absolute bottom-20 right-4 z-30 flex items-center gap-2">
    <!-- Recording-in-progress pill: live meter + timer + Stop -->
    <Transition name="rec-pop">
      <div
        v-if="recs.recording.value"
        class="flex items-center gap-2 pl-2.5 pr-1.5 py-1.5 rounded-full bg-surface border border-danger/40 shadow-lg"
      >
        <span class="relative flex h-2.5 w-2.5 shrink-0">
          <span class="absolute inline-flex h-full w-full rounded-full bg-danger opacity-60 animate-ping" />
          <span class="relative inline-flex h-2.5 w-2.5 rounded-full bg-danger" />
        </span>
        <canvas ref="canvas" width="96" height="28" class="shrink-0" />
        <span class="text-xs font-mono text-text-primary tabular-nums">{{ fmtTime(recs.elapsed.value) }}</span>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium bg-danger/20 text-danger hover:bg-danger/30 cursor-pointer transition-colors"
          title="Stop recording"
          @click="recs.toggleRecord()"
        >
          <Square :size="10" /> Stop
        </button>
      </div>
    </Transition>

    <!-- Saving state pill -->
    <Transition name="rec-pop">
      <div
        v-if="recs.uploading.value"
        class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full bg-surface border border-border shadow-lg"
      >
        <Loader :size="12" class="animate-spin text-accent" />
        <span class="text-[11px] text-text-secondary">Saving…</span>
      </div>
    </Transition>

    <!-- Floating action button: starts / stops capture -->
    <button
      class="flex items-center justify-center h-10 w-10 rounded-full shadow-lg cursor-pointer transition-all hover:scale-105"
      :class="recs.recording.value
        ? 'bg-danger text-white'
        : 'bg-accent text-white hover:bg-accent-hover'"
      :title="recs.hasEntry.value ? 'Record voice memo' : 'Save the entry, then record'"
      @click="recs.toggleRecord()"
    >
      <Square v-if="recs.recording.value" :size="16" />
      <Loader v-else-if="recs.uploading.value" :size="16" class="animate-spin" />
      <Mic v-else :size="18" />
    </button>
  </div>
</template>

<style scoped>
.rec-pop-enter-active,
.rec-pop-leave-active {
  transition: all 0.18s ease;
}
.rec-pop-enter-from,
.rec-pop-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
</style>
