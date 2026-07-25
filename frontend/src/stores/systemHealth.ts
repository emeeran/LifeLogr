import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getIntegrity, refreshIntegrity, type IntegrityReport } from '../api/system'

export const useSystemHealthStore = defineStore('systemHealth', () => {
  const report = ref<IntegrityReport | null>(null)
  const loaded = ref(false)
  const dismissed = ref(false)
  const refreshing = ref(false)

  const summary = computed(() => report.value?.summary ?? { ok: 0, warn: 0, error: 0 })
  const issueCount = computed(() => summary.value.warn + summary.value.error)
  const hasIssues = computed(() => issueCount.value > 0)
  const showBanner = computed(() => loaded.value && hasIssues.value && !dismissed.value)

  async function load() {
    try {
      report.value = await getIntegrity()
      loaded.value = true
    } catch {
      /* backend not ready or endpoint missing — banner simply won't show */
    }
  }

  async function refresh() {
    refreshing.value = true
    try {
      report.value = await refreshIntegrity()
      loaded.value = true
      dismissed.value = false
    } finally {
      refreshing.value = false
    }
  }

  function dismiss() {
    dismissed.value = true
  }

  return { report, loaded, dismissed, refreshing, summary, issueCount, hasIssues, showBanner, load, refresh, dismiss }
})
