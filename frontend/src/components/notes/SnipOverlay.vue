<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

// Fullscreen crop overlay shown after the desktop shell captures the screen.
// The captured screenshot is rendered as a background image; the user drags a
// rectangle and we crop that region (in source pixels) out of the image and
// emit it as a PNG File. Esc cancels.
const props = defineProps<{ src: string }>()
const emit = defineEmits<{
  cropped: [file: File]
  cancel: []
}>()

const img = ref<HTMLImageElement | null>(null)
const ready = ref(false)
// Drag selection in CSS pixels relative to the overlay.
const dragging = ref(false)
const start = ref({ x: 0, y: 0 })
const sel = ref({ x: 0, y: 0, w: 0, h: 0 })

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('cancel')
}
function pointerPos(e: PointerEvent) {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  return { x: e.clientX - r.left, y: e.clientY - r.top }
}
function onDown(e: PointerEvent) {
  const p = pointerPos(e)
  dragging.value = true
  start.value = p
  sel.value = { x: p.x, y: p.y, w: 0, h: 0 }
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}
function onMove(e: PointerEvent) {
  if (!dragging.value) return
  const p = pointerPos(e)
  sel.value = {
    x: Math.min(start.value.x, p.x),
    y: Math.min(start.value.y, p.y),
    w: Math.abs(p.x - start.value.x),
    h: Math.abs(p.y - start.value.y),
  }
}
function onUp() {
  if (!dragging.value) return
  dragging.value = false
  // Ignore a click without a real drag.
  if (sel.value.w < 4 || sel.value.h < 4) return
  crop()
}
function crop() {
  const el = img.value
  if (!el) return emit('cancel')
  // The image is stretched to fill the overlay, so map the CSS-pixel selection
  // back to natural pixels with independent X/Y scales.
  const rect = el.getBoundingClientRect()
  const scaleX = el.naturalWidth / rect.width
  const scaleY = el.naturalHeight / rect.height
  const sourceX = Math.round(sel.value.x * scaleX)
  const sourceY = Math.round(sel.value.y * scaleY)
  const sourceW = Math.max(1, Math.round(sel.value.w * scaleX))
  const sourceH = Math.max(1, Math.round(sel.value.h * scaleY))
  const c = document.createElement('canvas')
  c.width = sourceW
  c.height = sourceH
  const ctx = c.getContext('2d')
  if (!ctx) return emit('cancel')
  ctx.drawImage(el, sourceX, sourceY, sourceW, sourceH, 0, 0, sourceW, sourceH)
  c.toBlob((blob) => {
    if (!blob) return emit('cancel')
    emit('cropped', new File([blob], 'snip.png', { type: 'image/png' }))
  }, 'image/png')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div
    class="snip-overlay"
    @pointerdown="onDown"
    @pointermove="onMove"
    @pointerup="onUp"
  >
    <img
      ref="img"
      :src="props.src"
      class="snip-img"
      @load="ready = true"
      alt=""
      draggable="false"
    />
    <div
      v-if="ready"
      class="snip-sel"
      :style="{ left: sel.x + 'px', top: sel.y + 'px', width: sel.w + 'px', height: sel.h + 'px' }"
    />
    <div class="snip-hint">Drag to select the region to clip · Esc to cancel</div>
    <button class="snip-x" title="Cancel (Esc)" @click="emit('cancel')">✕</button>
  </div>
</template>

<style scoped>
.snip-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: #000;
  cursor: crosshair;
  touch-action: none;
}
.snip-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: fill;
  user-select: none;
}
.snip-sel {
  position: absolute;
  border: 2px solid #fff;
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.45);
  pointer-events: none;
}
.snip-hint {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  pointer-events: none;
}
.snip-x {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;
}
.snip-x:hover { background: rgba(0, 0, 0, 0.85); }
</style>
