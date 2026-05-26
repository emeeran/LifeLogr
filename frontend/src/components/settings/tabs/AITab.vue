<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getThemes, pullModel } from '../../../api/ai'
import type { ThemeInsight } from '../../../types'
import { getSettings, updateSettings, getOllamaModels } from '../../../api/settings'
import type { AppSettings, AIModelInfo } from '../../../api/settings'
import { request } from '../../../api/client'
import {
  Brain, Sparkles, Loader, Download as DownloadIcon,
  Link, Wifi, WifiOff, Eye
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'
import SkeletonCard from '../shared/SkeletonCard.vue'
import AccordionItem from '../shared/AccordionItem.vue'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

function formatModelSize(bytes: number): string {
  if (!bytes) return ''
  const gb = bytes / (1024 ** 3)
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / (1024 ** 2)).toFixed(0)} MB`
}

// ── AI Configuration ──
const appSettings = ref<AppSettings | null>(null)
const ollamaModels = ref<AIModelInfo[]>([])
const settingsLoading = ref(false)
const aiSaving = ref(false)

async function loadAppSettings() {
  settingsLoading.value = true
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
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
  } finally { aiSaving.value = false }
}

// ── Connection Test ──
const connTesting = ref(false)
const connStatus = ref<{ ok: boolean; model: string; modelLoaded: boolean; embedAvailable: boolean } | null>(null)

async function testConnection() {
  connTesting.value = true
  connStatus.value = null
  try {
    const res = await request<{ ollama_available: boolean; model_name: string; model_loaded: boolean; embed_model_available: boolean; error: string | null }>('/ai/status')
    connStatus.value = {
      ok: res.ollama_available,
      model: res.model_name,
      modelLoaded: res.model_loaded,
      embedAvailable: res.embed_model_available,
    }
    if (!res.ollama_available) {
      emit('toast', 'error', `Ollama unavailable: ${res.error ?? 'connection refused'}`)
    } else {
      emit('toast', 'success', `Connected — ${res.model_name} ${res.model_loaded ? '(loaded)' : '(not loaded)'}`)
    }
  } catch (e: unknown) {
    connStatus.value = { ok: false, model: '', modelLoaded: false, embedAvailable: false }
    emit('toast', 'error', `Connection failed: ${errMsg(e)}`)
  } finally { connTesting.value = false }
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
  } finally { pulling.value = false }
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
  ai.ollama_model = 'llama3.1'
  ai.ollama_base_url = 'http://localhost:11434'
  ai.ollama_embed_model = 'nomic-embed-text'
  ai.enable_embeddings = true
  ai.enable_tag_suggestions = true
  ai.enable_sentiment = true
  ai.enable_summarization = true
  ai.enable_reflection_prompts = true
  ai.enable_writer_block_helper = true
  emit('toast', 'success', 'AI settings reset to defaults')
}

const availableEmbedModels = computed(() => {
  const names = ollamaModels.value.map(m => m.name)
  // Always include common embed models as suggestions
  const suggestions = ['nomic-embed-text', 'mxbai-embed-large', 'all-minilm']
  const all = [...new Set([...names.filter(n => n.includes('embed') || n.includes('e5') || n.includes('minilm')), ...suggestions])]
  return all
})

onMounted(() => {
  loadAppSettings()
  loadOllamaModels()
})
</script>

<template>
  <!-- AI Configuration -->
  <SettingsSection title="AI Configuration" :icon="Brain" description="Local AI model and feature settings"
    reset-label="Reset" @reset="resetAIDefaults">

    <template v-if="settingsLoading">
      <SkeletonCard :lines="4" />
    </template>

    <template v-else-if="appSettings">
      <!-- Connection -->
      <div class="border-t border-border pt-2.5 space-y-2 first:border-t-0 first:pt-0">
        <p class="text-[10px] text-text-muted uppercase tracking-wide">Connection</p>
        <SettingRow :icon="Link" label="Ollama URL">
          <input v-model="appSettings.ai.ollama_base_url" placeholder="http://localhost:11434"
            class="settings-input w-40" />
        </SettingRow>
        <div class="flex items-center gap-2 pl-[30px]">
          <button @click="testConnection" :disabled="connTesting"
            class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors disabled:opacity-50">
            <Loader v-if="connTesting" :size="11" class="animate-spin" />
            <Wifi v-else :size="11" /> Test Connection
          </button>
          <template v-if="connStatus">
            <span class="flex items-center gap-1 text-[10px]" :class="connStatus.ok ? 'text-green-400' : 'text-red-400'">
              <Wifi v-if="connStatus.ok" :size="10" />
              <WifiOff v-else :size="10" />
              {{ connStatus.ok ? 'Connected' : 'Unreachable' }}
            </span>
          </template>
        </div>
      </div>

      <!-- Models -->
      <div class="border-t border-border pt-2.5 space-y-2">
        <p class="text-[10px] text-text-muted uppercase tracking-wide">Models</p>
        <SettingRow :icon="Sparkles" label="Chat model">
          <select v-model="appSettings.ai.ollama_model" class="settings-select max-w-40">
            <option v-for="m in ollamaModels" :key="m.name" :value="m.name">
              {{ m.name }} {{ m.size ? `(${formatModelSize(m.size)})` : '' }}
            </option>
            <option :value="appSettings.ai.ollama_model">{{ appSettings.ai.ollama_model }} (current)</option>
          </select>
        </SettingRow>
        <SettingRow :icon="Eye" label="Embedding model">
          <input v-model="appSettings.ai.ollama_embed_model" list="embed-models"
            placeholder="nomic-embed-text" class="settings-input w-40" />
          <datalist id="embed-models">
            <option v-for="m in availableEmbedModels" :key="m" :value="m" />
          </datalist>
        </SettingRow>
        <p class="text-[10px] text-text-muted pl-[30px]">Used for semantic search and finding similar entries.</p>
      </div>

      <!-- Feature toggles -->
      <div class="border-t border-border pt-2.5 space-y-2">
        <p class="text-[10px] text-text-muted uppercase tracking-wide">Features</p>
        <div class="grid grid-cols-2 gap-x-4 gap-y-2">
          <div v-for="(label, key) in ({
            enable_embeddings: 'Embeddings',
            enable_tag_suggestions: 'Tag suggestions',
            enable_sentiment: 'Sentiment analysis',
            enable_summarization: 'Summarization',
            enable_reflection_prompts: 'Reflection prompts',
            enable_writer_block_helper: 'Writer\'s block helper',
          } as Record<string, string>)" :key="key"
            class="flex items-center justify-between gap-2">
            <span class="text-[11px] text-text-secondary">{{ label }}</span>
            <ToggleSwitch v-model="(appSettings.ai as any)[key]" />
          </div>
        </div>
      </div>

      <!-- Save -->
      <button @click="saveAISettings" :disabled="aiSaving"
        class="flex items-center gap-1.5 px-3 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
        <Loader v-if="aiSaving" :size="11" class="animate-spin" />
        Save AI Settings
      </button>

      <!-- Pull model -->
      <div class="border-t border-border pt-2.5 space-y-2">
        <p class="text-[10px] text-text-muted uppercase tracking-wide">Download</p>
        <SettingRow :icon="DownloadIcon" label="Pull new model">
          <div class="flex items-center gap-1.5">
            <input v-model="pullModelName" placeholder="e.g. llama3.2:3b" class="settings-input w-40" />
            <button @click="handlePullModel" :disabled="pulling || !pullModelName.trim()"
              class="flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
              <Loader v-if="pulling" :size="11" class="animate-spin" /> Pull
            </button>
          </div>
        </SettingRow>
        <p v-if="pullStatus" class="text-[10px] text-text-muted pl-[30px]">{{ pullStatus }}</p>
      </div>
    </template>
  </SettingsSection>

  <!-- Themes & Insights (collapsible) -->
  <AccordionItem title="Themes & Insights" :icon="Brain" description="Discover patterns in your journaling">
    <div class="space-y-3">
      <SettingRow label="Analyze journaling themes over">
        <div class="flex items-center gap-1.5">
          <select v-model.number="themesMonths" class="settings-select w-20">
            <option v-for="m in [1,3,6,12,24]" :key="m" :value="m">{{ m }} month{{ m > 1 ? 's' : '' }}</option>
          </select>
          <button @click="fetchThemes" :disabled="themesLoading"
            class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
            <Loader v-if="themesLoading" :size="11" class="animate-spin" />
            <Sparkles v-else :size="11" /> Analyze
          </button>
        </div>
      </SettingRow>
      <div v-if="themes.length" class="space-y-2 max-h-60 overflow-y-auto">
        <div v-for="(t, i) in themes" :key="i" class="p-2.5 bg-surface-hover rounded-md space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-[12px] font-medium text-text-primary">{{ t.theme }}</span>
            <span class="text-[11px] text-accent">{{ t.frequency }}</span>
          </div>
          <div v-if="t.months_mentioned.length" class="text-[10px] text-text-muted">
            Months: {{ t.months_mentioned.join(', ') }}
          </div>
          <div v-if="t.insight" class="text-[11px] text-text-secondary">{{ t.insight }}</div>
        </div>
      </div>
      <div v-else-if="!themesLoading" class="text-center py-3">
        <Sparkles :size="18" class="mx-auto text-text-muted mb-1" />
        <p class="text-[11px] text-text-secondary">No theme analysis yet.</p>
        <p class="text-[10px] text-text-muted">Click Analyze to discover patterns in your entries.</p>
      </div>
    </div>
  </AccordionItem>
</template>
