import { defineStore } from 'pinia'
import { ref } from 'vue'
import { globalSearch, type SearchMode } from '../api/search'
import type { SearchResultEntry } from '../types'
import { useLocalStorage } from '@vueuse/core'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

const MAX_HISTORY = 10

export const useSearchStore = defineStore('search', () => {
  const results = ref<SearchResultEntry[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const searchMode = useLocalStorage<SearchMode>(
    'lifelogr-search-mode',
    'hybrid',
  )
  const searchHistory = useLocalStorage<string[]>('lifelogr-search-history', [])
  const queryDuration = ref(0)

  async function search(
    query: string,
    params?: { mood?: string; offset?: number; limit?: number },
  ) {
    if (!query.trim()) {
      clear()
      return
    }
    loading.value = true
    error.value = null
    const startTime = performance.now()
    try {
      const p = { ...params, mode: searchMode.value }
      const res = await globalSearch(query, p)
      results.value = res.items
      total.value = res.total
    } catch (e: unknown) {
      // Stale results from a previous query must not linger behind an error.
      results.value = []
      total.value = 0
      const message = errorMessage(e) || 'Search failed'
      error.value = message
      useToastStore().error(`Search failed: ${message}`)
    } finally {
      queryDuration.value = Math.round(performance.now() - startTime)
      loading.value = false
    }
  }

  /** Record a query in the persisted history. Called on EXPLICIT user intent
   *  only (opening a result / pressing Enter in the palette) — never from
   *  `search()`, which fires on every debounced keystroke and used to flood
   *  the history with half-typed fragments. */
  function addToHistory(query: string) {
    const q = query.trim()
    if (!q) return
    const idx = searchHistory.value.indexOf(q)
    if (idx >= 0) searchHistory.value.splice(idx, 1)
    searchHistory.value.unshift(q)
    if (searchHistory.value.length > MAX_HISTORY) searchHistory.value.pop()
  }

  function clear() {
    results.value = []
    total.value = 0
    queryDuration.value = 0
    error.value = null
  }

  return {
    results,
    total,
    loading,
    error,
    searchMode,
    searchHistory,
    queryDuration,
    search,
    addToHistory,
    clear,
  }
})
