<script setup lang="ts">
/**
 * MediaViewer — full-screen lightbox for images / video / audio / docs.
 *
 * Enhancements:
 *  • Zoom toolbar (reset / in / out / fit) with percentage indicator.
 *  • Keyboard hints and a clean caption + filename + size footer.
 *  • Download action in the toolbar; caption shown beneath the media.
 *  • Drag-to-pan when zoomed in on an image.
 *  • Video uses native controls (relies on backend range support).
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'
import {
  X, ChevronLeft, ChevronRight, Download, ZoomIn, ZoomOut, Maximize2,
} from 'lucide-vue-next'
import { mediaApi } from '../../api/media'
import { formatFileSize } from '../../composables/useFormat'
import type { MediaResponse } from '../../types'

const props = defineProps<{ items: MediaResponse[]; startIndex?: number }>()
const emit = defineEmits<{ close: [] }>()

const index = defineModel<number>('index', { default: 0 })

const isImage = (type: string) => type === 'image' || type.startsWith('image/')
const isVideo = (type: string) => type === 'video' || type.startsWith('video/')
const isAudio = (type: string) => type === 'audio' || type.startsWith('audio/')

const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const dragging = ref(false)
let dragStart = { x: 0, y: 0, px: 0, py: 0 }

const current = computed(() => props.items[index.value])
const fileUrl = computed(() => current.value ? mediaApi.fileUrl(current.value.id) : '')
const typeLabel = computed(() => {
  if (!current.value) return ''
  const t = current.value.media_type
  if (isImage(t)) return 'Image'
  if (isVideo(t)) return 'Video'
  if (isAudio(t)) return 'Audio'
  return 'Document'
})

function prev() { if (index.value > 0) { index.value--; resetZoom() } }
function next() { if (index.value < props.items.length - 1) { index.value++; resetZoom() } }
function resetZoom() { zoom.value = 1; panX.value = 0; panY.value = 0 }
function zoomIn() { zoom.value = Math.min(8, +(zoom.value + 0.25).toFixed(2)) }
function zoomOut() { zoom.value = Math.max(0.25, +(zoom.value - 0.25).toFixed(2)); if (zoom.value === 1) resetZoom() }

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
  else if (e.key === '+' || e.key === '=') zoomIn()
  else if (e.key === '-' || e.key === '_') zoomOut()
  else if (e.key === '0') resetZoom()
}

function onWheel(e: WheelEvent) {
  // Only zoom images; let native controls handle video/audio scroll.
  if (current.value && isImage(current.value.media_type)) {
    e.preventDefault()
    if (e.deltaY < 0) zoomIn(); else zoomOut()
  }
}

// Drag-to-pan for zoomed images.
function onPointerDown(e: PointerEvent) {
  if (zoom.value <= 1) return
  dragging.value = true
  dragStart = { x: e.clientX, y: e.clientY, px: panX.value, py: panY.value }
  ;(e.target as Element).setPointerCapture?.(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  panX.value = dragStart.px + (e.clientX - dragStart.x)
  panY.value = dragStart.py + (e.clientY - dragStart.y)
}
function onPointerUp() { dragging.value = false }

onMounted(() => {
  document.addEventListener('keydown', onKey)
  document.addEventListener('wheel', onWheel, { passive: false })
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKey)
  document.removeEventListener('wheel', onWheel)
})
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/92 backdrop-blur-sm flex items-center justify-center select-none"
    @click.self="emit('close')">
    <!-- Top toolbar -->
    <div class="absolute top-0 inset-x-0 z-20 flex items-center justify-between px-4 py-3 bg-gradient-to-b from-black/70 to-transparent">
      <span class="text-[12px] text-white/80 font-medium truncate max-w-[40%]">
        {{ current?.filename }}
      </span>

      <div class="flex items-center gap-1.5">
        <!-- Zoom controls (images only) -->
        <template v-if="current && isImage(current.media_type)">
          <button class="toolbar-btn" title="Zoom out (−)" @click="zoomOut"><ZoomOut :size="16" /></button>
          <button class="toolbar-btn !px-2 min-w-[3rem]" title="Reset zoom (0)" @click="resetZoom">
            {{ Math.round(zoom * 100) }}%
          </button>
          <button class="toolbar-btn" title="Zoom in (+)" @click="zoomIn"><ZoomIn :size="16" /></button>
        </template>

        <a v-if="current" :href="fileUrl" :download="current.filename" title="Download"
          class="toolbar-btn"><Download :size="16" /></a>
        <button class="toolbar-btn" title="Close (Esc)" @click="emit('close')"><X :size="18" /></button>
      </div>
    </div>

    <!-- Nav arrows -->
    <button v-if="index > 0" class="nav-btn left-4" @click="prev"><ChevronLeft :size="26" /></button>
    <button v-if="index < items.length - 1" class="nav-btn right-4" @click="next"><ChevronRight :size="26" /></button>

    <!-- Content -->
    <template v-if="current">
      <!-- Image (zoom + pan) -->
      <img
        v-if="isImage(current.media_type)"
        :src="fileUrl"
        :alt="current.filename"
        class="max-w-full max-h-[calc(100vh-7rem)] object-contain transition-transform duration-100"
        :class="{ 'cursor-grab': zoom > 1, 'cursor-grabbing': dragging }"
        :style="{ transform: `translate(${panX}px, ${panY}px) scale(${zoom})` }"
        draggable="false"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @dblclick="zoom === 1 ? zoomIn() : resetZoom()"
      />

      <!-- Video -->
      <video
        v-else-if="isVideo(current.media_type)"
        :src="fileUrl"
        :poster="''"
        controls
        autoplay
        preload="metadata"
        class="max-w-full max-h-[calc(100vh-7rem)] rounded-lg shadow-2xl"
      >
        Your browser does not support video playback.
      </video>

      <!-- Audio -->
      <div v-else-if="isAudio(current.media_type)" class="flex flex-col items-center gap-5 px-6">
        <div class="w-28 h-28 rounded-full bg-gradient-to-br from-accent/30 to-accent/10 flex items-center justify-center shadow-lg">
          <svg viewBox="0 0 24 24" class="w-12 h-12 text-accent" fill="currentColor">
            <path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/>
          </svg>
        </div>
        <p class="text-sm text-white/90 font-medium text-center max-w-md truncate">{{ current.filename }}</p>
        <audio :src="fileUrl" controls autoplay preload="metadata" class="w-80 max-w-full" />
      </div>

      <!-- Document -->
      <div v-else class="flex flex-col items-center gap-4 text-white px-6">
        <div class="w-24 h-24 rounded-2xl bg-white/10 flex items-center justify-center">
          <Maximize2 :size="36" class="text-white/60" />
        </div>
        <p class="text-sm text-white/80 text-center max-w-md">{{ current.filename }}</p>
        <a :href="fileUrl" :download="current.filename"
          class="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover transition-colors">
          <Download :size="16" /> Download
        </a>
      </div>

      <!-- Footer: caption + position + meta -->
      <div class="absolute bottom-0 inset-x-0 z-20 px-4 py-3 bg-gradient-to-t from-black/80 to-transparent">
        <p v-if="current.caption" class="text-center text-[13px] text-white/90 italic max-w-2xl mx-auto mb-1.5">
          “{{ current.caption }}”
        </p>
        <div class="flex items-center justify-center gap-2 text-[11px] text-white/60">
          <span class="font-medium text-white/80">{{ index + 1 }} / {{ items.length }}</span>
          <span>·</span>
          <span>{{ typeLabel }}</span>
          <span>·</span>
          <span>{{ formatFileSize(current.file_size) }}</span>
          <span v-if="items.length > 1" class="hidden sm:inline">·</span>
          <span v-if="items.length > 1" class="hidden sm:inline">← → to navigate · Esc to close</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.toolbar-btn {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 0.4rem; border-radius: 0.5rem;
  background: rgba(255,255,255,0.1); color: #fff;
  cursor: pointer; transition: background 0.15s;
}
.toolbar-btn:hover { background: rgba(255,255,255,0.22); }

.nav-btn {
  position: absolute; padding: 0.6rem; border-radius: 9999px; z-index: 10;
  background: rgba(255,255,255,0.1); color: #fff; cursor: pointer;
  transition: background 0.15s;
}
.nav-btn:hover { background: rgba(255,255,255,0.25); }
</style>
