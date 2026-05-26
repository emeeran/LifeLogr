<script setup lang="ts">
import { ref, onMounted, watch, reactive, computed } from 'vue'
import { entriesApi } from '../../api/entries'
import { mediaApi } from '../../api/media'
import { useUiStore } from '../../stores/ui'
import { useEntriesStore } from '../../stores/entries'
import { useTagsStore } from '../../stores/tags'
import { usePagination } from '../../composables/usePagination'
import { formatEntryDate } from '../../composables/useFormat'
import { ChevronLeft, ChevronRight, Tag, X, Calendar } from 'lucide-vue-next'
import GoToDateModal from '../common/GoToDateModal.vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import type { EntryResponse } from '../../types'

const ui = useUiStore()
const store = useEntriesStore()
const tagsStore = useTagsStore()
const pagination = usePagination(20)
const entries = ref<EntryResponse[]>([])
const filterTagId = ref<number | null>(null)
const showTagMenu = ref(false)
const showGoToDate = ref(false)

const filteredEntries = computed(() =>
  entries.value.filter(e => filterTagId.value === null || e.tags.some(t => t.id === filterTagId))
)

// Virtual scrolling
const scrollEl = ref<HTMLElement | null>(null)
const virtualizer = useVirtualizer(
  computed(() => ({
    count: filteredEntries.value.length,
    getScrollElement: () => scrollEl.value,
    estimateSize: () => 100,
    overscan: 5,
  })),
)

// Lazy media thumbnail cache: entryId → first media URL
const thumbnailMap = reactive<Record<number, string>>({})

async function load() {
  const res = await entriesApi.list({ offset: pagination.offset.value, limit: pagination.limit.value })
  entries.value = res.items
  pagination.total.value = res.total
  // Lazy-load thumbnails for entries with media
  for (const e of res.items) {
    if (e.media_count > 0 && !thumbnailMap[e.id]) {
      loadThumbnail(e.id)
    }
  }
}

async function loadThumbnail(entryId: number) {
  try {
    const media = await mediaApi.listByEntry(entryId)
    const img = media.find(m => m.media_type === 'image' || m.media_type.startsWith('image/'))
    if (img) thumbnailMap[entryId] = mediaApi.fileUrl(img.id)
  } catch { /* ignore */ }
}

onMounted(() => { load(); tagsStore.fetchTree() })
watch(() => store.lastUpdated, load)

function openEntry(entry: EntryResponse) {
  ui.requestEdit(entry.id)
}

const activeTagName = () => {
  if (filterTagId.value === null) return null
  return tagsStore.tags.find(t => t.id === filterTagId.value)?.name ?? null
}

const shortDateOpts: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }

function bodyPreview(body: string): string {
  const lines = body.split('\n').filter(l => l.trim())
  const first2 = lines.slice(0, 2).join(' / ')
  return first2.length > 140 ? first2.slice(0, 140) + '...' : first2
}

async function onGoToDate(dateStr: string) {
  const [y, m] = dateStr.split('-').map(Number)
  pagination.offset.value = 0
  const res = await entriesApi.list({ offset: 0, limit: pagination.limit.value, year: y, month: m })
  entries.value = res.items
  pagination.total.value = res.total
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="px-4 py-3 border-b border-border flex items-center gap-2">
      <h2 class="text-lg font-semibold text-text-primary">Timeline</h2>
      <button
        class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
        title="Go to date"
        @click="showGoToDate = true"
      >
        <Calendar :size="11" /> Go to
      </button>
      <!-- Tag filter -->
      <div v-if="tagsStore.tags.length" class="flex items-center gap-1.5 relative ml-auto">
        <button
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium cursor-pointer transition-colors"
          :class="filterTagId !== null ? 'bg-accent text-white' : 'bg-surface-hover text-text-secondary hover:text-text-primary'"
          @click="showTagMenu = !showTagMenu"
        >
          <Tag :size="11" />
          <span v-if="activeTagName()">#{{ activeTagName() }}</span>
          <span v-else>Filter</span>
        </button>
        <button
          v-if="filterTagId !== null"
          class="text-text-muted hover:text-text-primary cursor-pointer"
          @click="filterTagId = null"
          title="Clear filter"
        >
          <X :size="12" />
        </button>
        <!-- Tag dropdown -->
        <div
          v-if="showTagMenu"
          class="absolute top-full right-0 mt-1 bg-surface border border-border rounded-lg shadow-xl py-1 min-w-[140px] max-h-[200px] overflow-y-auto z-50"
        >
          <button
            v-for="tag in tagsStore.tags"
            :key="tag.id"
            class="w-full text-left px-3 py-1 text-[11px] cursor-pointer transition-colors"
            :class="filterTagId === tag.id ? 'bg-accent/15 text-accent' : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'"
            @click="filterTagId = tag.id; showTagMenu = false"
          >
            #{{ tag.name }}
          </button>
          <div class="border-t border-border my-0.5" />
          <button
            class="w-full text-left px-3 py-1 text-[11px] text-text-muted hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            @click="filterTagId = null; showTagMenu = false"
          >
            Show all
          </button>
        </div>
      </div>
    </div>

    <div ref="scrollEl" class="flex-1 overflow-y-auto">
      <div
        :style="{ height: `${virtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }"
      >
        <div
          v-for="virtualRow in virtualizer.getVirtualItems()"
          :key="virtualRow.key"
          :style="{ position: 'absolute', top: 0, left: 0, width: '100%', height: `${virtualRow.size}px`, transform: `translateY(${virtualRow.start}px)` }"
          class="px-4 py-3 border-b border-border/50 hover:bg-surface-hover cursor-pointer transition-colors"
          @click="openEntry(filteredEntries[virtualRow.index])"
        >
          <div class="flex gap-3">
            <!-- Entry content (left) -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-medium text-text-primary">{{ formatEntryDate(filteredEntries[virtualRow.index].entry_date, shortDateOpts) }}</span>
              </div>
              <p v-if="filteredEntries[virtualRow.index].title" class="text-xs font-medium text-text-primary mb-0.5">{{ filteredEntries[virtualRow.index].title }}</p>
              <p class="text-xs text-text-secondary leading-relaxed whitespace-pre-line">
                {{ filteredEntries[virtualRow.index].is_encrypted ? 'Encrypted' : bodyPreview(filteredEntries[virtualRow.index].body) }}
              </p>
              <div v-if="filteredEntries[virtualRow.index].tags.length" class="flex flex-wrap gap-1 mt-1">
                <span v-for="tag in filteredEntries[virtualRow.index].tags" :key="tag.id" class="text-[10px] px-1.5 py-0.5 rounded-full bg-accent/15 text-accent">#{{ tag.name }}</span>
              </div>
            </div>
            <!-- Media thumbnail (right) -->
            <div v-if="thumbnailMap[filteredEntries[virtualRow.index].id]" class="shrink-0 self-center">
              <img
                :src="thumbnailMap[filteredEntries[virtualRow.index].id]"
                class="w-14 h-14 rounded object-cover border border-border/50"
                loading="lazy"
              />
            </div>
          </div>
        </div>
      </div>

      <div v-if="entries.length === 0" class="p-8 text-center text-text-muted text-sm">
        No entries yet.
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="pagination.totalPages.value > 1" class="flex items-center justify-between px-4 py-2 border-t border-border">
      <span class="text-xs text-text-muted">Page {{ pagination.page.value }} of {{ pagination.totalPages.value }}</span>
      <div class="flex gap-1">
        <button
          :disabled="!pagination.hasPrev.value"
          class="p-1 rounded hover:bg-surface-hover text-text-secondary disabled:opacity-30 cursor-pointer transition-colors"
          @click="pagination.prevPage(); load()"
        >
          <ChevronLeft :size="16" />
        </button>
        <button
          :disabled="!pagination.hasNext.value"
          class="p-1 rounded hover:bg-surface-hover text-text-secondary disabled:opacity-30 cursor-pointer transition-colors"
          @click="pagination.nextPage(); load()"
        >
          <ChevronRight :size="16" />
        </button>
      </div>
    </div>

    <GoToDateModal v-model="showGoToDate" @select="onGoToDate" />
  </div>
</template>
