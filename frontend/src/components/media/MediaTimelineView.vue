<script setup lang="ts">
/**
 * MediaTimelineView — browse all media grouped by entry/date.
 *
 * Enhancements:
 *  • Real video thumbnails (first frame via a muted <video> element).
 *  • Audio tiles get a waveform glyph and a play affordance.
 *  • Filter chips show live counts.
 *  • Rich empty state; lazy-loaded images; hover overlay with size + type.
 *  • Click opens the (enhanced) MediaViewer lightbox.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { mediaApi } from '../../api/media'
import { usePagination } from '../../composables/usePagination'
import { formatEntryDate, formatFileSize } from '../../composables/useFormat'
import { useUiStore } from '../../stores/ui'
import {
  ChevronLeft, ChevronRight, Film, Music, FileText, Play, ImageIcon, FolderOpen,
  Eye, Trash2, ExternalLink,
} from 'lucide-vue-next'
import MediaViewer from './MediaViewer.vue'
import type { MediaTimelineItem, MediaResponse } from '../../types'

const ui = useUiStore()

const pagination = usePagination(40)
const items = ref<MediaTimelineItem[]>([])
const filter = ref<string>('all')
const loading = ref(false)
const viewerOpen = ref(false)
const viewerItems = ref<MediaResponse[]>([])
const viewerIndex = ref(0)

const isImage = (t: string) => t === 'image' || t.startsWith('image/')
const isVideo = (t: string) => t === 'video' || t.startsWith('video/')
const isAudio = (t: string) => t === 'audio' || t.startsWith('audio/')

const filters = computed(() => [
  { key: 'all', label: 'All', count: pagination.total.value },
  { key: 'image', label: 'Images', count: items.value.filter(i => isImage(i.media_type)).length },
  { key: 'video', label: 'Videos', count: items.value.filter(i => isVideo(i.media_type)).length },
  { key: 'audio', label: 'Audio', count: items.value.filter(i => isAudio(i.media_type)).length },
])

const dateGroups = computed(() => {
  const groups: Record<string, { entry_id: number; date: string; title: string | null; items: MediaTimelineItem[] }> = {}
  for (const item of items.value) {
    const key = `${item.entry_date}-${item.entry_id}`
    if (!groups[key]) groups[key] = { entry_id: item.entry_id, date: item.entry_date, title: item.entry_title, items: [] }
    groups[key].items.push(item)
  }
  return Object.values(groups)
})

const dateOpts: Intl.DateTimeFormatOptions = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }

async function load() {
  loading.value = true
  try {
    const mediaType = filter.value === 'all' ? undefined : filter.value
    const res = await mediaApi.listAll({
      offset: pagination.offset.value,
      limit: pagination.limit.value,
      media_type: mediaType,
    })
    items.value = res.items
    pagination.total.value = res.total
  } finally {
    loading.value = false
  }
}

function openViewer(groupItems: MediaTimelineItem[], index: number) {
  viewerItems.value = groupItems
  viewerIndex.value = index
  viewerOpen.value = true
}

function setFilter(key: string) {
  filter.value = key
  pagination.offset.value = 0
  load()
}

async function remove(item: MediaTimelineItem) {
  if (!confirm(`Delete "${item.filename}"?`)) return
  try {
    await mediaApi.delete(item.id)
    items.value = items.value.filter(i => i.id !== item.id)
    pagination.total.value = Math.max(0, pagination.total.value - 1)
  } catch {
    alert('Failed to delete media. It may have already been removed.')
  }
}

/** Open the journal entry this media belongs to in the editor. */
function openEntry(entryId: number, date: string) {
  ui.requestEdit(entryId, date)
}

onMounted(load)
watch(() => filter.value, load)
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="px-4 py-3 border-b border-border flex items-center gap-2 flex-wrap">
      <h2 class="text-base font-semibold text-text-primary mr-2 flex items-center gap-1.5">
        <ImageIcon :size="15" class="text-accent" /> Media
      </h2>
      <div class="flex gap-1 flex-wrap">
        <button v-for="f in filters" :key="f.key" type="button"
          class="px-2.5 py-1 rounded-full text-[10.5px] font-medium cursor-pointer transition-colors inline-flex items-center gap-1.5 border"
          :class="filter === f.key
            ? 'bg-accent text-white border-accent'
            : 'bg-surface-hover text-text-secondary hover:text-text-primary border-border'"
          @click="setFilter(f.key)">
          {{ f.label }}
          <span class="px-1 rounded-full text-[9px]"
            :class="filter === f.key ? 'bg-white/25' : 'bg-border/60'">{{ f.count }}</span>
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="loading" class="text-center text-text-muted text-sm py-12">Loading media…</div>

      <template v-else-if="items.length">
        <div v-for="group in dateGroups" :key="group.date + (group.title ?? '')" class="mb-7">
          <!-- Date header -->
          <div class="mb-2.5 flex items-baseline gap-2">
            <h3 class="text-[13px] font-semibold text-text-primary">
              {{ formatEntryDate(group.date, dateOpts) }}
            </h3>
            <span class="text-[10px] text-text-muted">{{ group.items.length }} item{{ group.items.length === 1 ? '' : 's' }}</span>
          </div>
          <p v-if="group.title" class="text-[11px] text-text-secondary -mt-2 mb-2.5 italic">{{ group.title }}</p>

          <!-- Thumbnail grid -->
          <div class="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-8 gap-2">
            <div v-for="(item, idx) in group.items" :key="item.id"
              class="media-tile group relative rounded-lg overflow-hidden border border-border/60 bg-surface-hover cursor-pointer aspect-square flex items-center justify-center transition-all hover:border-accent/50 hover:shadow-md"
              @click="openViewer(group.items, idx)">

              <!-- Quick actions: View + Delete -->
              <div class="absolute top-1 right-1 z-10 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button type="button" title="View"
                  class="flex items-center justify-center w-6 h-6 rounded-full bg-black/60 text-white hover:bg-accent transition-colors cursor-pointer"
                  @click.stop="openViewer(group.items, idx)">
                  <Eye :size="12" />
                </button>
                <button type="button" title="Delete"
                  class="flex items-center justify-center w-6 h-6 rounded-full bg-black/60 text-white hover:bg-danger transition-colors cursor-pointer"
                  @click.stop="remove(item)">
                  <Trash2 :size="12" />
                </button>
              </div>

              <!-- Image -->
              <img v-if="isImage(item.media_type)" :src="mediaApi.fileUrl(item.id)" :alt="item.filename"
                class="w-full h-full object-cover" loading="lazy" decoding="async" />

              <!-- Video: first-frame thumbnail via muted <video> -->
              <template v-else-if="isVideo(item.media_type)">
                <video :src="mediaApi.fileUrl(item.id)" muted preload="metadata"
                  class="w-full h-full object-cover" @loadeddata="(e) => (e.target as HTMLVideoElement).currentTime = Math.min(0.1, (e.target as HTMLVideoElement).duration || 0)" />
                <div class="absolute inset-0 flex items-center justify-center bg-black/25">
                  <div class="w-9 h-9 rounded-full bg-black/60 backdrop-blur-sm flex items-center justify-center group-hover:scale-110 group-hover:bg-accent transition-all">
                    <Play :size="15" class="text-white fill-white ml-0.5" />
                  </div>
                </div>
                <span class="absolute top-1 left-1 px-1 py-0.5 rounded bg-black/60 text-white text-[8px] font-medium flex items-center gap-0.5">
                  <Film :size="8" /> VIDEO
                </span>
              </template>

              <!-- Audio -->
              <template v-else-if="isAudio(item.media_type)">
                <div class="flex flex-col items-center justify-center gap-1.5 w-full h-full p-1">
                  <div class="w-10 h-10 rounded-full bg-accent/15 flex items-center justify-center group-hover:bg-accent/25 transition-colors">
                    <Music :size="16" class="text-accent" />
                  </div>
                  <!-- faux waveform -->
                  <div class="flex items-end gap-0.5 h-4">
                    <span v-for="h in [6,12,8,14,10,7,12,9]" :key="h"
                      class="w-0.5 bg-accent/50 rounded-full" :style="{ height: h + 'px' }" />
                  </div>
                </div>
                <span class="absolute top-1 left-1 px-1 py-0.5 rounded bg-black/60 text-white text-[8px] font-medium flex items-center gap-0.5">
                  <Music :size="8" /> AUDIO
                </span>
              </template>

              <!-- Document -->
              <template v-else>
                <div class="flex flex-col items-center justify-center gap-1 w-full h-full p-2 text-text-secondary">
                  <FileText :size="22" class="text-accent/70" />
                  <span class="text-[9px] text-center truncate w-full">{{ item.filename }}</span>
                </div>
                <span class="absolute top-1 left-1 px-1 py-0.5 rounded bg-black/60 text-white text-[8px] font-medium">
                  DOC
                </span>
              </template>

              <!-- Hover overlay -->
              <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 pt-3 pb-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <p class="text-white text-[9px] truncate">{{ item.filename }}</p>
                <p class="text-white/70 text-[8.5px]">{{ formatFileSize(item.file_size) }}</p>
              </div>
            </div>
          </div>

          <!-- Jump to the journal entry this group belongs to -->
          <div class="mt-2 flex justify-end">
            <button type="button"
              class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10.5px] text-text-secondary hover:text-accent hover:bg-accent/10 border border-border/60 transition-colors cursor-pointer"
              @click="openEntry(group.entry_id, group.date)">
              <ExternalLink :size="11" /> Open in editor
            </button>
          </div>
        </div>
      </template>

      <!-- Empty state -->
      <div v-else class="flex flex-col items-center justify-center py-16 text-center">
        <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-3">
          <FolderOpen :size="24" class="text-accent/70" />
        </div>
        <h3 class="text-[14px] font-medium text-text-primary">No media yet</h3>
        <p class="text-[12px] text-text-secondary mt-1 max-w-xs leading-relaxed">
          Attach photos, recordings, or documents to your journal entries and
          they'll appear here in a browsable timeline.
        </p>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="pagination.totalPages.value > 1" class="flex items-center justify-between px-4 py-2 border-t border-border">
      <span class="text-[11px] text-text-muted">Page {{ pagination.page.value }} of {{ pagination.totalPages.value }}</span>
      <div class="flex gap-1">
        <button :disabled="!pagination.hasPrev.value"
          class="p-1 rounded hover:bg-surface-hover text-text-secondary disabled:opacity-30 cursor-pointer transition-colors"
          @click="pagination.prevPage(); load()">
          <ChevronLeft :size="16" />
        </button>
        <button :disabled="!pagination.hasNext.value"
          class="p-1 rounded hover:bg-surface-hover text-text-secondary disabled:opacity-30 cursor-pointer transition-colors"
          @click="pagination.nextPage(); load()">
          <ChevronRight :size="16" />
        </button>
      </div>
    </div>

    <!-- Lightbox -->
    <MediaViewer v-if="viewerOpen" :items="viewerItems" v-model:index="viewerIndex" @close="viewerOpen = false" />
  </div>
</template>
