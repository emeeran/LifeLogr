<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useSearchStore } from '../../stores/search'
import { useUiStore } from '../../stores/ui'
import { useTagsStore } from '../../stores/tags'
import { Search as SearchIcon, Calendar, Hash, ArrowRight } from 'lucide-vue-next'
import DOMPurify from 'dompurify'
import type { SearchResultEntry } from '../../types'

const searchStore = useSearchStore()
const ui = useUiStore()
const tagsStore = useTagsStore()

const query = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const selectedIndex = ref(0)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const results = computed(() => searchStore.results)

watch(query, (q) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!q.trim()) { searchStore.clear(); return }
  debounceTimer = setTimeout(() => searchStore.search(q), 200)
  selectedIndex.value = 0
})

onMounted(() => {
  nextTick(() => inputRef.value?.focus())
  if (!tagsStore.tags.length) tagsStore.fetchAll()
})
onUnmounted(() => { if (debounceTimer) clearTimeout(debounceTimer) })

function openEntry(item: SearchResultEntry) {
  ui.startEditing(item.id)
  ui.closeSearchPalette()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { ui.closeSearchPalette(); return }
  if (e.key === 'ArrowDown') { e.preventDefault(); selectedIndex.value = Math.min(selectedIndex.value + 1, results.value.length - 1); return }
  if (e.key === 'ArrowUp') { e.preventDefault(); selectedIndex.value = Math.max(selectedIndex.value - 1, 0); return }
  if (e.key === 'Enter' && results.value.length) { openEntry(results.value[selectedIndex.value]); return }
}

const shortDateOpts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString(undefined, shortDateOpts)
}

function sanitize(html: string) {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['mark'], ALLOWED_ATTR: [] })
}
</script>

<template>
  <div class="fixed inset-0 z-[300] flex items-start justify-center pt-[15vh] bg-black/40" @click.self="ui.closeSearchPalette()">
    <div class="bg-surface border border-border rounded-xl w-[560px] max-h-[60vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Input -->
      <div class="flex items-center gap-2 px-4 py-3 border-b border-border">
        <SearchIcon :size="18" class="text-text-muted shrink-0" />
        <input
          ref="inputRef"
          v-model="query"
          class="flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted"
          placeholder="Search entries... (Ctrl+K)"
          @keydown="onKeydown"
        />
        <!-- Search mode toggle -->
        <div class="flex bg-surface-hover rounded-md overflow-hidden border border-border text-[10px]">
          <button v-for="m in (['keyword', 'semantic', 'hybrid'] as const)" :key="m"
            @click="searchStore.searchMode = m; if (query) searchStore.search(query)"
            class="px-1.5 py-0.5 transition-colors"
            :class="searchStore.searchMode === m ? 'bg-accent text-white' : 'text-text-muted hover:text-text-primary'"
            :title="m === 'keyword' ? 'Exact text match' : m === 'semantic' ? 'AI meaning-based' : 'Combined results'"
          >{{ m === 'keyword' ? 'Aa' : m === 'semantic' ? 'AI' : 'Mix' }}</button>
        </div>
        <kbd class="hidden sm:inline text-[10px] text-text-muted bg-surface-hover border border-border rounded px-1.5 py-0.5">Esc</kbd>
      </div>

      <!-- Tag filters (clickable pills) -->
      <div v-if="tagsStore.tags.length" class="flex gap-1 px-4 py-2 border-b border-border overflow-x-auto">
        <button
          v-for="tag in tagsStore.tags.slice(0, 10)"
          :key="tag.id"
          class="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border cursor-pointer transition-colors"
          :class="searchStore.activeTagIds.includes(tag.id)
            ? 'bg-accent/20 text-accent border-accent/30'
            : 'bg-surface-hover text-text-secondary border-border hover:text-text-primary'"
          @click="searchStore.toggleTag(tag.id); searchStore.search(query)"
        >
          <Hash :size="8" />{{ tag.name }}
        </button>
      </div>

      <!-- Results -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="searchStore.loading" class="px-4 py-8 text-center text-text-muted text-xs flex items-center justify-center gap-2">
          <SearchIcon :size="12" class="animate-pulse" /> Searching...
        </div>

        <div v-else-if="query && !results.length" class="px-4 py-8 text-center text-text-muted text-xs">
          No results for "{{ query }}"
        </div>

        <div v-else-if="!query" class="px-4 py-6 text-center text-text-muted text-xs">
          Type to search across all entries
        </div>

        <div
          v-for="(item, i) in results"
          :key="item.id"
          class="flex items-start gap-3 px-4 py-2.5 cursor-pointer transition-colors"
          :class="i === selectedIndex ? 'bg-accent/10' : 'hover:bg-surface-hover'"
          @click="openEntry(item)"
          @mouseenter="selectedIndex = i"
        >
          <Calendar :size="13" class="text-text-muted mt-0.5 shrink-0" />
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-xs font-medium text-text-primary">{{ formatDate(item.entry_date) }}</span>
              <span v-if="item.title" class="text-xs text-text-secondary truncate">{{ item.title }}</span>
            </div>
            <p class="text-[11px] text-text-muted leading-relaxed mt-0.5 line-clamp-2" v-html="sanitize(item.snippet)" />
          </div>
          <ArrowRight v-if="i === selectedIndex" :size="12" class="text-accent mt-1 shrink-0" />
        </div>
      </div>

      <!-- Footer -->
      <div v-if="results.length" class="flex items-center justify-between px-4 py-2 border-t border-border text-[10px] text-text-muted">
        <span>{{ searchStore.total }} result{{ searchStore.total === 1 ? '' : 's' }}</span>
        <div class="flex items-center gap-3">
          <span class="flex items-center gap-1"><kbd class="bg-surface-hover border border-border rounded px-1 py-px">&uarr;&darr;</kbd> navigate</span>
          <span class="flex items-center gap-1"><kbd class="bg-surface-hover border border-border rounded px-1 py-px">Enter</kbd> open</span>
        </div>
      </div>
    </div>
  </div>
</template>
