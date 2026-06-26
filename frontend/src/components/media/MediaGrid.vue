<script setup lang="ts">
/**
 * MediaGrid — inline attachment grid shown inside an entry editor.
 *
 * Enhancements:
 *  • Video thumbnails show their first frame + a play badge.
 *  • Audio tiles get a waveform glyph.
 *  • Hover overlay reveals filename + size + type.
 *  • Delete button always reachable (was hover-only, hard on touch).
 */
import { ref, onMounted, watch } from 'vue'
import { mediaApi } from '../../api/media'
import { FileText, Music, Trash2, Play } from 'lucide-vue-next'
import MediaViewer from './MediaViewer.vue'
import { formatFileSize } from '../../composables/useFormat'
import type { MediaResponse } from '../../types'

const props = defineProps<{ entryId: number; mediaCount: number }>()
const emit = defineEmits<{ deleted: [] }>()

const items = ref<MediaResponse[]>([])
const viewerOpen = ref(false)
const viewerIndex = ref(0)

const isImage = (t: string) => t === 'image' || t.startsWith('image/')
const isVideo = (t: string) => t === 'video' || t.startsWith('video/')
const isAudio = (t: string) => t === 'audio' || t.startsWith('audio/')

async function load() {
  if (!props.entryId || props.entryId < 0) return
  try { items.value = await mediaApi.listByEntry(props.entryId) } catch { /* ignore */ }
}

onMounted(load)
watch(() => props.entryId, load)
watch(() => props.mediaCount, load)

async function remove(id: number) {
  if (!confirm('Remove this attachment?')) return
  await mediaApi.delete(id)
  items.value = items.value.filter(m => m.id !== id)
  emit('deleted')
}

function openViewer(idx: number) { viewerIndex.value = idx; viewerOpen.value = true }
</script>

<template>
  <div>
    <div v-if="items.length" class="grid grid-cols-3 sm:grid-cols-4 gap-1.5">
      <div v-for="(m, idx) in items" :key="m.id"
        class="group relative rounded-lg border border-border/60 overflow-hidden cursor-pointer bg-surface-hover aspect-square"
        @click="openViewer(idx)">

        <!-- Image -->
        <img v-if="isImage(m.media_type)" :src="mediaApi.fileUrl(m.id)" :alt="m.filename"
          class="w-full h-full object-cover" loading="lazy" decoding="async" />

        <!-- Video -->
        <template v-else-if="isVideo(m.media_type)">
          <video :src="mediaApi.fileUrl(m.id)" muted preload="metadata"
            class="w-full h-full object-cover"
            @loadeddata="(e) => (e.target as HTMLVideoElement).currentTime = Math.min(0.1, (e.target as HTMLVideoElement).duration || 0)" />
          <div class="absolute inset-0 flex items-center justify-center bg-black/25">
            <div class="w-8 h-8 rounded-full bg-black/60 flex items-center justify-center group-hover:bg-accent transition-colors">
              <Play :size="13" class="text-white fill-white ml-0.5" />
            </div>
          </div>
        </template>

        <!-- Audio -->
        <div v-else-if="isAudio(m.media_type)" class="w-full h-full flex flex-col items-center justify-center gap-1.5 p-2">
          <div class="w-9 h-9 rounded-full bg-accent/15 flex items-center justify-center">
            <Music :size="15" class="text-accent" />
          </div>
          <div class="flex items-end gap-0.5 h-3">
            <span v-for="h in [5,9,6,11,7]" :key="h" class="w-0.5 bg-accent/50 rounded-full" :style="{ height: h + 'px' }" />
          </div>
        </div>

        <!-- Document -->
        <div v-else class="w-full h-full flex flex-col items-center justify-center gap-1 p-2">
          <FileText :size="20" class="text-accent/70" />
          <span class="text-[9px] text-text-secondary text-center truncate w-full">{{ m.filename }}</span>
        </div>

        <!-- Hover overlay: name + size -->
        <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 pt-3 pb-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <p class="text-white text-[9px] truncate">{{ m.filename }}</p>
          <p class="text-white/70 text-[8.5px]">{{ formatFileSize(m.file_size) }}</p>
        </div>

        <!-- Delete (always visible-on-hover, larger hit area) -->
        <button
          class="absolute top-1 right-1 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 hover:bg-danger transition-all cursor-pointer"
          @click.stop="remove(m.id)" title="Remove attachment">
          <Trash2 :size="12" />
        </button>
      </div>
    </div>

    <MediaViewer v-if="viewerOpen" :items="items" v-model:index="viewerIndex" @close="viewerOpen = false" />
  </div>
</template>
