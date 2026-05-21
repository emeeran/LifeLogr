<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getLatestDigest, generateDigest, listDigests } from '../../api/ai'
import type { DigestResponse } from '../../types'
import { BookOpen, RefreshCw, Loader, Calendar, Sparkles } from 'lucide-vue-next'

const latest = ref<DigestResponse | null>(null)
const pastDigests = ref<DigestResponse[]>([])
const loading = ref(false)
const generating = ref(false)
const error = ref('')

async function loadDigests() {
  loading.value = true
  error.value = ''
  try {
    const [latestRes, list] = await Promise.all([getLatestDigest(), listDigests(10)])
    latest.value = latestRes
    pastDigests.value = list.filter(d => d.id !== latestRes?.id)
  } catch (e: any) {
    error.value = e.message || 'Failed to load digests'
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    const digest = await generateDigest()
    latest.value = digest
    pastDigests.value = [digest, ...pastDigests.value.filter(d => d.id !== digest.id)]
  } catch (e: any) {
    error.value = e.message || 'Failed to generate digest'
  } finally {
    generating.value = false
  }
}

function formatDate(d: string) {
  return new Date(d + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

onMounted(loadDigests)
</script>

<template>
  <div class="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-lg font-semibold text-text-primary flex items-center gap-2">
        <BookOpen :size="20" /> Weekly Digest
      </h1>
      <button @click="generate()" :disabled="generating"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-xs rounded-lg hover:bg-accent/90 disabled:opacity-50">
        <Loader v-if="generating" :size="12" class="animate-spin" />
        <RefreshCw v-else :size="12" />
        Generate Now
      </button>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16 text-text-muted text-sm">
      <Loader :size="16" class="animate-spin mr-2" /> Loading digests...
    </div>

    <div v-else-if="error" class="text-center py-16 text-red-400 text-sm">{{ error }}</div>

    <div v-else-if="!latest && !pastDigests.length" class="text-center py-16">
      <Sparkles :size="32" class="text-text-muted mx-auto mb-3" />
      <p class="text-text-muted text-sm">No digests yet. Entries need to be saved first for AI to analyze them.</p>
      <p class="text-text-muted text-xs mt-2">Click "Generate Now" to create your first weekly digest.</p>
    </div>

    <div v-else>
      <!-- Latest digest -->
      <div v-if="latest" class="bg-surface-hover rounded-xl p-5 border border-border mb-6">
        <div class="flex items-center gap-2 text-xs text-text-muted mb-3">
          <Calendar :size="12" />
          {{ formatDate(latest.week_start) }} — {{ formatDate(latest.week_end) }}
        </div>

        <!-- Themes -->
        <div v-if="latest.themes.length" class="flex gap-1.5 flex-wrap mb-3">
          <span v-for="theme in latest.themes" :key="theme"
            class="px-2 py-0.5 bg-accent/10 text-accent text-[10px] rounded-full">{{ theme }}</span>
        </div>

        <!-- Summary -->
        <p class="text-sm text-text-primary leading-relaxed mb-4">{{ latest.summary_text }}</p>

        <!-- Emotional trajectory -->
        <div v-if="latest.emotional_trajectory" class="mb-3">
          <span class="text-[10px] text-text-muted uppercase tracking-wider">Emotional Arc</span>
          <p class="text-xs text-text-secondary mt-1">{{ latest.emotional_trajectory }}</p>
        </div>

        <!-- Notable moments -->
        <div v-if="latest.notable_moments.length">
          <span class="text-[10px] text-text-muted uppercase tracking-wider">Notable Moments</span>
          <ul class="mt-1 space-y-1">
            <li v-for="(moment, i) in latest.notable_moments" :key="i" class="text-xs text-text-secondary flex items-start gap-1.5">
              <span class="text-accent mt-0.5">-</span> {{ moment }}
            </li>
          </ul>
        </div>
      </div>

      <!-- Past digests -->
      <div v-if="pastDigests.length">
        <h2 class="text-sm font-medium text-text-secondary mb-3">Past Digests</h2>
        <div class="space-y-2">
          <div v-for="d in pastDigests" :key="d.id"
            class="bg-surface-hover/50 rounded-lg p-3 border border-border/50">
            <div class="flex items-center gap-2 text-xs text-text-muted mb-1">
              <Calendar :size="10" />
              {{ formatDate(d.week_start) }} — {{ formatDate(d.week_end) }}
            </div>
            <p class="text-xs text-text-secondary line-clamp-2">{{ d.summary_text }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
