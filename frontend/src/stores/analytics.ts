import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as analyticsApi from '../api/analytics'
import type { OverviewResponse, WritingHabitResponse, WordCountResponse, TagStatsResponse, HeatmapResponse, MediaStatsResponse } from '../types'

export const useAnalyticsStore = defineStore('analytics', () => {
  const overview = ref<OverviewResponse | null>(null)
  const habits = ref<WritingHabitResponse[]>([])
  const wordCounts = ref<WordCountResponse | null>(null)
  const tagStats = ref<TagStatsResponse[]>([])
  const heatmap = ref<HeatmapResponse | null>(null)
  const mediaStats = ref<MediaStatsResponse | null>(null)
  const loading = ref(false)

  async function fetchOverview() {
    loading.value = true
    try { overview.value = await analyticsApi.getOverview() }
    finally { loading.value = false }
  }

  async function fetchHabits() {
    habits.value = await analyticsApi.getHabits()
  }

  async function fetchWordCounts() {
    wordCounts.value = await analyticsApi.getWords()
  }

  async function fetchTagStats() {
    tagStats.value = await analyticsApi.getTagStats()
  }

  async function fetchHeatmap(year?: number) {
    heatmap.value = await analyticsApi.getHeatmap(year)
  }

  async function fetchMediaStats() {
    mediaStats.value = await analyticsApi.getMediaStats()
  }

  async function fetchAll(year?: number) {
    loading.value = true
    try {
      await Promise.all([
        fetchOverview(),
        fetchHabits(),
        fetchWordCounts(),
        fetchTagStats(),
        fetchHeatmap(year),
        fetchMediaStats(),
      ])
    } finally {
      loading.value = false
    }
  }

  return { overview, habits, wordCounts, tagStats, heatmap, mediaStats, loading, fetchOverview, fetchHabits, fetchWordCounts, fetchTagStats, fetchHeatmap, fetchMediaStats, fetchAll }
})
