<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { X, ChevronLeft, ChevronRight, Download } from 'lucide-vue-next'
import { mediaApi } from '../../api/media'
import type { MediaResponse } from '../../types'

const props = defineProps<{ items: MediaResponse[]; startIndex?: number }>()
const emit = defineEmits<{ close: [] }>()

const index = defineModel<number>('index', { default: 0 })
const isImage = (type: string) => type === 'image' || type.startsWith('image/')
const isVideo = (type: string) => type === 'video' || type.startsWith('video/')
const isAudio = (type: string) => type === 'audio' || type.startsWith('audio/')

const zoom = ref(0.5)

const current = computed(() => props.items[index.value])
const fileUrl = computed(() => current.value ? mediaApi.fileUrl(current.value.id) : '')

function prev() { if (index.value > 0) { index.value--; zoom.value = 0.5 } }
function next() { if (index.value < props.items.length - 1) { index.value++; zoom.value = 0.5 } }

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  zoom.value = Math.min(5, Math.max(0.25, zoom.value + (e.deltaY < 0 ? 0.15 : -0.15)))
}

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
  <div class="fixed inset-0 z-50 bg-black/90 flex items-center justify-center" @click.self="emit('close')">
    <!-- Close -->
    <button
      class="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white cursor-pointer z-10"
      @click="emit('close')"
    >
      <X :size="24" />
    </button>

    <!-- Nav arrows -->
    <button
      v-if="index > 0"
      class="absolute left-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white cursor-pointer z-10"
      @click="prev"
    >
      <ChevronLeft :size="24" />
    </button>
    <button
      v-if="index < items.length - 1"
      class="absolute right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white cursor-pointer z-10"
      @click="next"
    >
      <ChevronRight :size="24" />
    </button>

    <!-- Content -->
    <template v-if="current">
      <!-- Image -->
      <img
        v-if="isImage(current.media_type)"
        :src="fileUrl"
        :alt="current.filename"
        class="max-w-full max-h-[calc(100vh-6rem)] object-contain p-4 transition-transform duration-150"
        :style="{ transform: `scale(${zoom})` }"
      />

      <!-- Video -->
      <video
        v-else-if="isVideo(current.media_type)"
        :src="fileUrl"
        controls
        class="max-w-full max-h-[calc(100vh-6rem)] transition-transform duration-150"
        :style="{ transform: `scale(${zoom})` }"
      />

      <!-- Audio -->
      <div v-else-if="isAudio(current.media_type)" class="flex flex-col items-center gap-4 text-white">
        <p class="text-sm text-white/70">{{ current.filename }}</p>
        <audio :src="fileUrl" controls class="w-80" />
      </div>

      <!-- Document (download) -->
      <div v-else class="flex flex-col items-center gap-4 text-white">
        <p class="text-sm text-white/70">{{ current.filename }}</p>
        <a
          :href="fileUrl"
          :download="current.filename"
          class="flex items-center gap-2 px-4 py-2 rounded bg-accent text-white text-sm hover:bg-accent-hover"
        >
          <Download :size="16" />
          Download
        </a>
      </div>

      <!-- Filename bar -->
      <div class="absolute bottom-2 left-1/2 -translate-x-1/2 text-xs text-white/60 whitespace-nowrap">
        {{ index + 1 }} / {{ items.length }} — {{ current.filename }}
        <span v-if="zoom !== 1" class="ml-2">{{ Math.round(zoom * 100) }}%</span>
      </div>
    </template>
  </div>
</template>
