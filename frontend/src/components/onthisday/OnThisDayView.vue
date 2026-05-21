<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getOnThisDay } from '../../api/ai'
import type { OnThisDayResponse } from '../../types'
import { Sunrise, Calendar, Loader, Sparkles, RefreshCw, BookOpen } from 'lucide-vue-next'

const data = ref<OnThisDayResponse | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getOnThisDay()
  } catch (e: any) {
    error.value = e.message || 'Failed to load'
  } finally {
    loading.value = false
  }
}

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

onMounted(load)
</script>

<template>
  <div class="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-lg font-semibold text-text-primary flex items-center gap-2">
        <Sunrise :size="20" /> On This Day
      </h1>
      <button @click="load()" :disabled="loading"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-xs rounded-lg hover:bg-accent/90 disabled:opacity-50">
        <Loader v-if="loading" :size="12" class="animate-spin" />
        <RefreshCw v-else :size="12" />
        Refresh
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-16 text-text-muted text-sm">
      <Loader :size="16" class="animate-spin mr-2" /> Reflecting on past entries...
    </div>

    <!-- Error -->
    <div v-else-if="error" class="text-center py-16 text-red-400 text-sm">{{ error }}</div>

    <!-- No entries -->
    <div v-else-if="data && data.entries_count === 0" class="text-center py-16">
      <Sparkles :size="32" class="text-text-muted mx-auto mb-3" />
      <p class="text-text-muted text-sm">No entries found on this date in previous years.</p>
      <p class="text-text-muted text-xs mt-2">Keep journaling and come back next year!</p>
    </div>

    <!-- Content -->
    <div v-else-if="data">
      <!-- Date header -->
      <div class="text-center mb-8">
        <div class="inline-flex items-center gap-2 px-4 py-2 bg-accent/10 rounded-full mb-3">
          <Calendar :size="14" class="text-accent" />
          <span class="text-sm text-accent font-medium">{{ formatDate(new Date().toISOString().slice(0, 10)) }}</span>
        </div>
        <p class="text-text-secondary text-sm">
          {{ data.entries_count }} past {{ data.entries_count === 1 ? 'entry' : 'entries' }} found on this day
        </p>
      </div>

      <!-- AI Reflection -->
      <div class="bg-surface-hover rounded-xl p-5 border border-border mb-6">
        <div class="flex items-center gap-2 mb-3">
          <Sparkles :size="14" class="text-accent" />
          <span class="text-xs font-medium text-accent uppercase tracking-wider">AI Reflection</span>
        </div>
        <p class="text-sm text-text-primary leading-relaxed">{{ data.reflection }}</p>
      </div>

      <!-- Past entries -->
      <div v-if="data.past_entries.length">
        <h2 class="text-sm font-medium text-text-secondary mb-3 flex items-center gap-2">
          <BookOpen :size="14" /> Past Entries
        </h2>
        <div class="space-y-3">
          <div v-for="entry in data.past_entries" :key="entry.date"
            class="bg-surface-hover/50 rounded-lg p-4 border border-border/50">
            <div class="flex items-center gap-2 text-xs text-text-muted mb-1.5">
              <Calendar :size="10" />
              <span class="font-medium">{{ formatDate(entry.date) }}</span>
              <span class="text-accent">{{ entry.years_ago }} {{ entry.years_ago === 1 ? 'year' : 'years' }} ago</span>
            </div>
            <p v-if="entry.title" class="text-sm font-medium text-text-primary mb-1">{{ entry.title }}</p>
            <p v-if="entry.snippet" class="text-xs text-text-secondary line-clamp-3">{{ entry.snippet }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
