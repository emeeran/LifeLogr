<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getThemes, pullModel } from '../../../api/ai'
import type { ThemeInsight } from '../../../types'
import { getSettings, updateSettings, getOllamaModels } from '../../../api/settings'
import type { AppSettings, AIModelInfo } from '../../../api/settings'
import {
  Brain, Sparkles, Loader, Download as DownloadIcon
} from 'lucide-vue-next'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

// ── AI Configuration ──
const appSettings = ref<AppSettings | null>(null)
const ollamaModels = ref<AIModelInfo[]>([])
const settingsLoading = ref(false)
const aiSaving = ref(false)

async function loadAppSettings() {
  settingsLoading.value = true
  try {
    appSettings.value = await getSettings()
  } catch { /* ignore */ }
  finally { settingsLoading.value = false }
}

async function loadOllamaModels() {
  try { ollamaModels.value = await getOllamaModels() } catch { /* ignore */ }
}

async function saveAISettings() {
  if (!appSettings.value) return
  aiSaving.value = true
  try {
    await updateSettings({ ai: appSettings.value.ai })
    emit('toast', 'success', 'AI settings saved')
  } catch (e: unknown) {
    emit('toast', 'error', `Save failed: ${errMsg(e)}`)
  } finally {
    aiSaving.value = false
  }
}

// ── Pull AI Model ──
const pullModelName = ref('')
const pulling = ref(false)
const pullStatus = ref('')

async function handlePullModel() {
  if (!pullModelName.value.trim()) return
  pulling.value = true
  pullStatus.value = 'Pulling...'
  try {
    await pullModel(pullModelName.value.trim())
    pullStatus.value = `Pull started for ${pullModelName.value.trim()}`
    emit('toast', 'success', `Model pull started: ${pullModelName.value.trim()}`)
  } catch (e: unknown) {
    pullStatus.value = `Failed: ${errMsg(e)}`
    emit('toast', 'error', `Pull failed: ${errMsg(e)}`)
  } finally {
    pulling.value = false
  }
}

// ── AI Themes & Insights ──
const themesMonths = ref(6)
const themes = ref<ThemeInsight[]>([])
const themesLoading = ref(false)

async function fetchThemes() {
  themesLoading.value = true
  try {
    const res = await getThemes(themesMonths.value)
    themes.value = res.themes
  } catch (e: unknown) { emit('toast', 'error', `Themes failed: ${errMsg(e)}`) }
  finally { themesLoading.value = false }
}

function resetAIDefaults() {
  if (!appSettings.value) return
  const ai = appSettings.value.ai
  ai.enable_embeddings = true
  ai.enable_tag_suggestions = true
  ai.enable_sentiment = true
  ai.enable_summarization = true
  ai.enable_reflection_prompts = true
  ai.enable_writer_block_helper = true
  emit('toast', 'success', 'AI features reset to defaults')
}

onMounted(() => {
  loadAppSettings()
  loadOllamaModels()
})
</script>

<template>
  <!-- AI Configuration -->
  <section>
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1">
        <Brain :size="11" /> AI Configuration
      </h3>
      <button @click="resetAIDefaults"
        class="text-[9px] text-text-muted hover:text-accent cursor-pointer transition-colors">Reset defaults</button>
    </div>
    <div class="bg-surface rounded p-2 border border-border space-y-2">
      <div v-if="settingsLoading" class="text-[10px] text-text-muted">Loading...</div>
      <template v-else-if="appSettings">
        <!-- Model selector -->
        <div class="flex items-center gap-2">
          <Sparkles :size="11" class="text-text-muted" />
          <span class="text-[11px] text-text-secondary flex-1">Ollama model</span>
          <select v-model="appSettings.ai.ollama_model"
            class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]">
            <option v-for="m in ollamaModels" :key="m.name" :value="m.name">{{ m.name }}</option>
            <option :value="appSettings.ai.ollama_model">{{ appSettings.ai.ollama_model }} (current)</option>
          </select>
        </div>
        <!-- Feature toggles -->
        <div class="space-y-1 border-t border-border pt-1.5">
          <div class="text-[10px] text-text-muted uppercase tracking-wide mb-1">Features</div>
          <label v-for="(label, key) in ({
            enable_embeddings: 'Embeddings (semantic search)',
            enable_tag_suggestions: 'Tag suggestions',
            enable_sentiment: 'Sentiment analysis',
            enable_summarization: 'Entry summarization',
            enable_reflection_prompts: 'Reflection prompts',
            enable_writer_block_helper: 'Writer\'s block helper',
          } as Record<string, string>)" :key="key"
            class="flex items-center gap-2 cursor-pointer">
            <span class="text-[11px] text-text-secondary flex-1">{{ label }}</span>
            <input type="checkbox" v-model="(appSettings.ai as any)[key]" class="accent-accent" />
          </label>
        </div>
        <button @click="saveAISettings" :disabled="aiSaving"
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
          <Loader v-if="aiSaving" :size="10" class="animate-spin" />
          Save AI Settings
        </button>
      </template>
      <!-- Pull model -->
      <div class="flex items-center gap-2 pt-1.5 border-t border-border">
        <DownloadIcon :size="11" class="text-text-muted shrink-0" />
        <span class="text-[11px] text-text-secondary flex-1">Pull model</span>
        <input v-model="pullModelName" placeholder="e.g. llama3.2:3b"
          class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none w-32 hover:border-accent transition-colors" />
        <button @click="handlePullModel" :disabled="pulling || !pullModelName.trim()"
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
          <Loader v-if="pulling" :size="10" class="animate-spin" /> Pull
        </button>
      </div>
      <div v-if="pullStatus" class="text-[9px] text-text-muted">{{ pullStatus }}</div>
    </div>
  </section>

  <!-- AI Themes & Insights -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Brain :size="11" /> Themes &amp; Insights
    </h3>
    <div class="bg-surface rounded p-2 border border-border space-y-2">
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-text-secondary flex-1">Analyze journaling themes over</span>
        <select v-model.number="themesMonths"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors w-16">
          <option v-for="m in [1,3,6,12,24]" :key="m" :value="m">{{ m }} month{{ m > 1 ? 's' : '' }}</option>
        </select>
        <button @click="fetchThemes" :disabled="themesLoading"
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
          <Loader v-if="themesLoading" :size="10" class="animate-spin" />
          <Sparkles v-else :size="10" /> Analyze
        </button>
      </div>
      <div v-if="themes.length" class="space-y-1.5 max-h-60 overflow-y-auto">
        <div v-for="(t, i) in themes" :key="i" class="p-2 bg-surface-hover rounded space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-text-primary">{{ t.theme }}</span>
            <span class="text-[10px] text-accent">{{ t.frequency }}</span>
          </div>
          <div v-if="t.months_mentioned.length" class="text-[10px] text-text-muted">
            Months: {{ t.months_mentioned.join(', ') }}
          </div>
          <div v-if="t.insight" class="text-[11px] text-text-secondary">{{ t.insight }}</div>
        </div>
      </div>
      <div v-else-if="themesLoading" class="text-[10px] text-text-muted text-center py-2">Analyzing your journal...</div>
    </div>
  </section>
</template>
