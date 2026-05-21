import { defineStore } from 'pinia'
import { ref } from 'vue'
import { globalSearch, type SearchMode } from '../api/search'
import type { SearchResultEntry } from '../types'
import { useLocalStorage } from '@vueuse/core'

export const useSearchStore = defineStore('search', () => {
  const results = ref<SearchResultEntry[]>([])
  const total = ref(0)
  const loading = ref(false)
  const activeTagIds = ref<number[]>([])
  const searchMode = useLocalStorage<SearchMode>('diarium-search-mode', 'hybrid')

  async function search(query: string, params?: { tag_ids?: string; date_from?: string; date_to?: string; offset?: number; limit?: number }) {
    if (!query.trim()) { clear(); return }
    loading.value = true
    try {
      const p = { ...params, mode: searchMode.value }
      if (activeTagIds.value.length) p.tag_ids = activeTagIds.value.join(',')
      const res = await globalSearch(query, p)
      results.value = res.items
      total.value = res.total
    } finally {
      loading.value = false
    }
  }

  function toggleTag(id: number) {
    const idx = activeTagIds.value.indexOf(id)
    if (idx >= 0) activeTagIds.value.splice(idx, 1)
    else activeTagIds.value.push(id)
  }

  function clear() {
    results.value = []
    total.value = 0
  }

  return { results, total, loading, activeTagIds, searchMode, search, toggleTag, clear }
})
