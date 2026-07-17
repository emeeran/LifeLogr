<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAnalyticsStore } from '../../stores/analytics'
import { BarChart3, BookOpen, FileText, Image, Mic, TrendingUp, Calendar } from 'lucide-vue-next'

const store = useAnalyticsStore()
const selectedYear = ref(new Date().getFullYear())

onMounted(() => store.fetchAll(selectedYear.value))

function changeYear(delta: number) {
  selectedYear.value += delta
  store.fetchHeatmap(selectedYear.value)
}

const maxHeatmap = computed(() => {
  if (!store.heatmap?.days) return 1
  return Math.max(...store.heatmap.days.map(d => d.count), 1)
})

function heatColor(count: number): string {
  if (count === 0) return 'var(--color-surface-hover)'
  const intensity = Math.min(count / maxHeatmap.value, 1)
  const alpha = 0.3 + intensity * 0.7
  return `rgba(59, 130, 246, ${alpha})`
}
</script>

<template>
  <div class="h-full overflow-y-auto p-6 space-y-8">
    <h1 class="text-2xl font-bold text-text-primary flex items-center gap-2">
      <BarChart3 :size="24" /> Analytics
    </h1>

    <!-- Loading -->
    <div v-if="store.loading" class="text-text-secondary">Loading analytics...</div>

    <template v-else>
      <!-- Overview Cards -->
      <div v-if="store.overview" class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-surface rounded-lg p-4 border border-border">
          <div class="flex items-center gap-2 text-text-secondary text-sm mb-1"><BookOpen :size="16" /> Entries</div>
          <div class="text-2xl font-bold text-text-primary">{{ store.overview.total_entries }}</div>
        </div>
        <div class="bg-surface rounded-lg p-4 border border-border">
          <div class="flex items-center gap-2 text-text-secondary text-sm mb-1"><FileText :size="16" /> Words</div>
          <div class="text-2xl font-bold text-text-primary">{{ store.overview.total_words.toLocaleString() }}</div>
        </div>
        <div class="bg-surface rounded-lg p-4 border border-border">
          <div class="flex items-center gap-2 text-text-secondary text-sm mb-1"><TrendingUp :size="16" /> Current Streak</div>
          <div class="text-2xl font-bold text-accent">{{ store.overview.current_streak }} days</div>
        </div>
        <div class="bg-surface rounded-lg p-4 border border-border">
          <div class="flex items-center gap-2 text-text-secondary text-sm mb-1"><TrendingUp :size="16" /> Longest Streak</div>
          <div class="text-2xl font-bold text-text-primary">{{ store.overview.longest_streak }} days</div>
        </div>
      </div>

      <!-- Word Counts -->
      <div v-if="store.wordCounts" class="bg-surface rounded-lg p-4 border border-border">
        <h2 class="text-lg font-semibold text-text-primary mb-3">Word Statistics</h2>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div><span class="text-text-secondary">Total:</span> <span class="font-medium text-text-primary">{{ store.wordCounts.total_words.toLocaleString() }}</span></div>
          <div><span class="text-text-secondary">Average:</span> <span class="font-medium text-text-primary">{{ store.wordCounts.average_words_per_entry }}</span></div>
          <div><span class="text-text-secondary">Longest:</span> <span class="font-medium text-text-primary">{{ store.wordCounts.longest_entry_words }}</span></div>
          <div><span class="text-text-secondary">Shortest:</span> <span class="font-medium text-text-primary">{{ store.wordCounts.shortest_entry_words }}</span></div>
        </div>
      </div>

      <!-- Writing Habits -->
      <div v-if="store.habits.length" class="bg-surface rounded-lg p-4 border border-border">
        <h2 class="text-lg font-semibold text-text-primary mb-3">Writing Habits (by day of week)</h2>
        <div class="flex items-end gap-2 h-32">
          <div v-for="h in store.habits" :key="h.day_of_week" class="flex-1 flex flex-col items-center gap-1">
            <div class="w-full bg-accent/60 rounded-t transition-all" :style="{ height: `${Math.max((h.entry_count / Math.max(...store.habits.map(x => x.entry_count), 1)) * 100, 4)}%` }"></div>
            <span class="text-xs text-text-secondary">{{ h.day_name.slice(0, 3) }}</span>
          </div>
        </div>
      </div>

      <!-- Heatmap -->
      <div v-if="store.heatmap" class="bg-surface rounded-lg p-4 border border-border">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-lg font-semibold text-text-primary flex items-center gap-2"><Calendar :size="18" /> Contribution Heatmap</h2>
          <div class="flex items-center gap-2">
            <button @click="changeYear(-1)" class="px-2 py-1 text-sm bg-surface-hover rounded hover:bg-border text-text-secondary">&larr;</button>
            <span class="text-sm font-medium text-text-primary">{{ store.heatmap.year }}</span>
            <button @click="changeYear(1)" class="px-2 py-1 text-sm bg-surface-hover rounded hover:bg-border text-text-secondary">&rarr;</button>
          </div>
        </div>
        <div class="flex flex-wrap gap-[3px]">
          <div v-for="day in store.heatmap.days" :key="day.date"
            class="w-[12px] h-[12px] rounded-sm"
            :style="{ backgroundColor: heatColor(day.count) }"
            :title="`${day.date}: ${day.count} entries`">
          </div>
        </div>
      </div>

      <!-- Media Stats -->
      <div v-if="store.mediaStats" class="bg-surface rounded-lg p-4 border border-border">
        <h2 class="text-lg font-semibold text-text-primary mb-3">Media</h2>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div class="flex items-center gap-2"><Image :size="16" class="text-text-secondary" /> {{ store.mediaStats.total_images }} images</div>
          <div class="flex items-center gap-2"><FileText :size="16" class="text-text-secondary" /> {{ store.mediaStats.total_videos }} videos</div>
          <div class="flex items-center gap-2"><Mic :size="16" class="text-text-secondary" /> {{ store.mediaStats.total_recordings }} recordings</div>
          <div class="text-text-secondary">{{ (store.mediaStats.total_size_bytes / 1024 / 1024).toFixed(1) }} MB total</div>
        </div>
      </div>
    </template>
  </div>
</template>
