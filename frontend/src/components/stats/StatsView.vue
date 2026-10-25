<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Flame, FileText, Type, ImageIcon, Trophy } from 'lucide-vue-next'
import type { JournalStats } from '../../types'
import { entriesApi } from '../../api/entries'
import WeeklyBars from './WeeklyBars.vue'
import MoodBars from './MoodBars.vue'

const stats = ref<JournalStats | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    stats.value = await entriesApi.stats()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load statistics'
  } finally {
    loading.value = false
  }
})

const tiles = [
  { key: 'current_streak', label: 'Current streak', icon: Flame, unit: 'day' },
  { key: 'longest_streak', label: 'Longest streak', icon: Trophy, unit: 'day' },
  { key: 'total_entries', label: 'Entries', icon: FileText, unit: '' },
  { key: 'total_words', label: 'Words written', icon: Type, unit: '' },
] as const

const totalMedia = (s: JournalStats) => s.media.reduce((n, m) => n + m.count, 0)

function compact(n: number): string {
  return n >= 10000 ? `${(n / 1000).toFixed(1)}K` : n.toLocaleString()
}
</script>

<template>
  <div class="flex flex-col h-full overflow-auto custom-scrollbar">
    <div class="px-4 py-3 border-b border-border/50 shrink-0">
      <h1 class="text-sm font-semibold text-text-primary">Statistics</h1>
      <p class="text-[11px] text-text-muted">Your journaling at a glance</p>
    </div>

    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <p class="text-xs text-text-muted">Loading…</p>
    </div>

    <div v-else-if="error" class="flex-1 flex items-center justify-center">
      <p class="text-xs text-red-400">{{ error }}</p>
    </div>

    <div v-else-if="stats" class="p-4 space-y-4 max-w-3xl mx-auto w-full">
      <!-- Empty journal: zeros everywhere, no charts to misread -->
      <p
        v-if="stats.total_entries === 0"
        class="text-xs text-text-muted"
        data-testid="stats-empty"
      >
        No entries yet — statistics appear once you start writing.
      </p>

      <!-- KPI row -->
      <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
        <div
          v-for="t in tiles"
          :key="t.key"
          class="rounded-lg border border-border/50 bg-surface p-3"
        >
          <div class="flex items-center gap-1.5 text-[10px] text-text-muted">
            <component :is="t.icon" :size="11" />
            <span>{{ t.label }}</span>
          </div>
          <p class="mt-1 text-xl font-semibold text-text-primary">
            {{ compact(stats[t.key]) }}
            <span
              v-if="t.unit && stats[t.key] === 1"
              class="text-[10px] font-normal text-text-muted"
              >{{ t.unit }}</span
            >
            <span
              v-else-if="t.unit"
              class="text-[10px] font-normal text-text-muted"
              >{{ t.unit }}s</span
            >
          </p>
        </div>
        <div class="rounded-lg border border-border/50 bg-surface p-3">
          <div class="flex items-center gap-1.5 text-[10px] text-text-muted">
            <ImageIcon :size="11" />
            <span>Media attached</span>
          </div>
          <p class="mt-1 text-xl font-semibold text-text-primary">
            {{ compact(totalMedia(stats)) }}
          </p>
        </div>
      </div>

      <!-- Entries per week -->
      <div class="rounded-lg border border-border/50 bg-surface p-3">
        <h2 class="text-xs font-semibold text-text-primary mb-2">
          Entries per week
        </h2>
        <WeeklyBars :data="stats.weekly" />
      </div>

      <!-- Mood distribution -->
      <div class="rounded-lg border border-border/50 bg-surface p-3">
        <h2 class="text-xs font-semibold text-text-primary mb-2">Moods</h2>
        <p v-if="!stats.moods.length" class="text-xs text-text-muted">
          No moods recorded yet.
        </p>
        <MoodBars v-else :moods="stats.moods" />
      </div>
    </div>
  </div>
</template>
