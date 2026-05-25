import { defineStore } from 'pinia'
import { ref } from 'vue'
import { globalSearch, type SearchMode } from '../api/search'
import type { SearchResultEntry } from '../types'
import { useLocalStorage } from '@vueuse/core'

const MAX_HISTORY = 10

export const useSearchStore = defineStore('search', () => {
  const results = ref<SearchResultEntry[]>([])
  const total = ref(0)
  const loading = ref(false)
  const activeTagIds = ref<number[]>([])
  const searchMode = useLocalStorage<SearchMode>('diarium-search-mode', 'hybrid')
  const dateFrom = ref('')
  const dateTo = ref('')
  const searchHistory = useLocalStorage<string[]>('diarium-search-history', [])
  const queryDuration = ref(0)

  async function search(query: string, params?: { tag_ids?: string; date_from?: string; date_to?: string; mood?: string; offset?: number; limit?: number }) {
    if (!query.trim()) { clear(); return }
    loading.value = true
    const startTime = performance.now()
    try {
      const p = { ...params, mode: searchMode.value }
      if (activeTagIds.value.length) p.tag_ids = activeTagIds.value.join(',')
      if (dateFrom.value) p.date_from = dateFrom.value
      if (dateTo.value) p.date_to = dateTo.value
      const res = await globalSearch(query, p)
      results.value = res.items
      total.value = res.total
      // Add to history
      addToHistory(query.trim())
    } finally {
      queryDuration.value = Math.round(performance.now() - startTime)
      loading.value = false
    }
  }

  function addToHistory(query: string) {
    const idx = searchHistory.value.indexOf(query)
    if (idx >= 0) searchHistory.value.splice(idx, 1)
    searchHistory.value.unshift(query)
    if (searchHistory.value.length > MAX_HISTORY) searchHistory.value.pop()
  }

  function toggleTag(id: number) {
    const idx = activeTagIds.value.indexOf(id)
    if (idx >= 0) activeTagIds.value.splice(idx, 1)
    else activeTagIds.value.push(id)
  }

  function clear() {
    results.value = []
    total.value = 0
    queryDuration.value = 0
  }

  return { results, total, loading, activeTagIds, searchMode, dateFrom, dateTo, searchHistory, queryDuration, search, toggleTag, clear }
})
