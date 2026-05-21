<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { mediaApi } from '../../api/media'
import { Image, FileText, Film, Music, Trash2 } from 'lucide-vue-next'
import MediaViewer from './MediaViewer.vue'
import { formatFileSize } from '../../composables/useFormat'
import type { MediaResponse } from '../../types'

const props = defineProps<{ entryId: number; mediaCount: number }>()
const emit = defineEmits<{ deleted: [] }>()

const items = ref<MediaResponse[]>([])
const viewerOpen = ref(false)
const viewerIndex = ref(0)

async function load() {
  if (!props.entryId || props.entryId < 0) return
  try {
    items.value = await mediaApi.listByEntry(props.entryId)
  } catch { /* ignore */ }
}

onMounted(load)
watch(() => props.entryId, load)
watch(() => props.mediaCount, load)

async function remove(id: number) {
  await mediaApi.delete(id)
  items.value = items.value.filter(m => m.id !== id)
  emit('deleted')
}

function openViewer(idx: number) {
  viewerIndex.value = idx
  viewerOpen.value = true
}

function iconFor(type: string) {
  if (type === 'image' || type.startsWith('image/')) return Image
  if (type === 'video' || type.startsWith('video/')) return Film
  if (type === 'audio' || type.startsWith('audio/')) return Music
  return FileText
}
</script>

<template>
  <div>
    <div v-if="items.length" class="grid grid-cols-2 gap-1.5">
      <div
        v-for="(m, idx) in items"
        :key="m.id"
        class="group relative rounded bg-surface-hover border border-border/50 overflow-hidden cursor-pointer"
        @click="openViewer(idx)"
      >
        <!-- Image thumbnail -->
        <div v-if="m.media_type === 'image' || m.media_type.startsWith('image/')" class="aspect-square">
          <img
            :src="mediaApi.fileUrl(m.id)"
            :alt="m.filename"
            class="w-full h-full object-cover"
          />
        </div>
        <!-- Document / video / audio icon -->
        <div v-else class="aspect-square flex flex-col items-center justify-center gap-1 p-2">
          <component :is="iconFor(m.media_type)" :size="24" class="text-accent" />
          <span class="text-[10px] text-text-secondary text-center truncate w-full">{{ m.filename }}</span>
          <span class="text-[9px] text-text-muted">{{ formatFileSize(m.file_size) }}</span>
        </div>
        <!-- Delete button -->
        <button
          class="absolute top-1 right-1 p-0.5 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
          @click.stop="remove(m.id)"
          title="Remove attachment"
        >
          <Trash2 :size="12" />
        </button>
      </div>
    </div>

    <!-- Viewer overlay -->
    <MediaViewer
      v-if="viewerOpen"
      :items="items"
      v-model:index="viewerIndex"
      @close="viewerOpen = false"
    />
  </div>
</template>
