<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { getThemes, pullModel } from '../../../api/ai'
import type { ThemeInsight } from '../../../types'
import { getSettings, updateSettings, getOllamaModels } from '../../../api/settings'
import type { AppSettings, AIModelInfo } from '../../../api/settings'
import { request } from '../../../api/client'
import {
  Brain, Sparkles, Loader, Download as DownloadIcon,
  Link, Wifi, WifiOff, Eye,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'
import SkeletonCard from '../shared/SkeletonCard.vue'
import AccordionItem from '../shared/AccordionItem.vue'
import SettingGroup from '../shared/SettingGroup.vue'
import SButton from '../shared/SButton.vue'

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

// Dirty-state tracking: show a "Save" affordance only when edits are pending.
const aiDirty = ref(false)

async function loadAppSettings() {
  settingsLoading.value = true
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
  finally { settingsLoading.value = false; aiDirty.value = false }
}

// Watch for any change to the ai sub-object once loaded.
watch(() => appSettings.value?.ai, () => { if (appSettings.value) aiDirty.value = true }, { deep: true })

async function loadOllamaModels() {
  try { ollamaModels.value = await getOllamaModels() } catch { /* ignore */ }
}

async function saveAISettings() {
  if (!appSettings.value) return
  aiSaving.value = true
  try {
    await updateSettings({ ai: appSettings.value.ai })
    aiDirty.value = false
    emit('toast', 'success', 'AI settings saved')
  } catch (e: unknown) { emit('toast', 'error', `Save failed: ${errMsg(e)}`) }
  finally { aiSaving.value = false }
}

// ── Connection Test ──
const connTesting = ref(false)
const connStatus = ref<{ ok: boolean; model: string; modelLoaded: boolean; embedAvailable: boolean } | null>(null)

async function testConnection() {
  connTesting.value = true; connStatus.value = null
  try {
    const res = await request<{ ollama_available: boolean; model_name: string; model_loaded: boolean; embed_model_available: boolean; error: string | null }>('/ai/status')
    connStatus.value = { ok: res.ollama_available, model: res.model_name, modelLoaded: res.model_loaded, embedAvailable: res.embed_model_available }
    if (!res.ollama_available) emit('toast', 'error', `Ollama unavailable: ${res.error ?? 'connection refused'}`)
    else emit('toast', 'success', `Connected — ${res.model_name} ${res.model_loaded ? '(loaded)' : '(not loaded)'}`)
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
  pulling.value = true; pullStatus.value = 'Pulling...'
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
  try { themes.value = (await getThemes(themesMonths.value)).themes }
  catch (e: unknown) { emit('toast', 'error', `Themes failed: ${errMsg(e)}`) }
  finally { themesLoading.value = false }
}

function resetAIDefaults() {
  if (!appSettings.value) return
  const ai = appSettings.value.ai
  ai.ollama_model = 'llama3.1'; ai.ollama_base_url = 'http://localhost:11434'
  ai.ollama_embed_model = 'nomic-embed-text'
  ai.enable_embeddings = true; ai.enable_tag_suggestions = true
  ai.enable_sentiment = true; ai.enable_summarization = true
  ai.enable_reflection_prompts = true; ai.enable_writer_block_helper = true
  emit('toast', 'success', 'AI settings reset to defaults')
}

const availableEmbedModels = computed(() => {
  const names = ollamaModels.value.map(m => m.name)
  const suggestions = ['nomic-embed-text', 'mxbai-embed-large', 'all-minilm']
  return [...new Set([...names.filter(n => n.includes('embed') || n.includes('e5') || n.includes('minilm')), ...suggestions])]
})

// Feature toggles with descriptions + whether they need the embedding model.
const featureToggles = computed(() => [
  { key: 'enable_embeddings', label: 'Embeddings', desc: 'Generate vector embeddings. Required for semantic search.', needsEmbed: true },
  { key: 'enable_tag_suggestions', label: 'Tag suggestions', desc: 'Suggest tags for entries using the chat model.', needsEmbed: false },
  { key: 'enable_sentiment', label: 'Sentiment analysis', desc: 'Score the mood of each entry.', needsEmbed: false },
  { key: 'enable_summarization', label: 'Summarization', desc: 'Auto-generate entry summaries.', needsEmbed: false },
  { key: 'enable_reflection_prompts', label: 'Reflection prompts', desc: 'Offer writing prompts based on past entries.', needsEmbed: false },
  { key: 'enable_writer_block_helper', label: "Writer's block helper", desc: 'Suggest continuations while writing.', needsEmbed: false },
] as const)

onMounted(() => { loadAppSettings(); loadOllamaModels() })
</script>

<template>
  <SettingsSection title="AI Configuration" :icon="Brain" description="Local AI model and feature settings" setting-key="Ollama URL"
    reset-label="Reset" @reset="resetAIDefaults">

    <template v-if="settingsLoading"><SkeletonCard :lines="4" /></template>

    <template v-else-if="appSettings">
      <SettingGroup label="Connection">
        <SettingRow :icon="Link" label="Ollama URL" description="Base URL of your local Ollama server.">
          <input v-model="appSettings.ai.ollama_base_url" placeholder="http://localhost:11434" class="settings-input w-44" />
        </SettingRow>
        <div class="flex items-center gap-2 pl-[31px]">
          <SButton variant="outline" :disabled="connTesting" @click="testConnection">
            <Loader v-if="connTesting" :size="12" class="animate-spin" /><Wifi v-else :size="12" /> Test Connection
          </SButton>
          <span v-if="connStatus" class="flex items-center gap-1 text-[11px]" :class="connStatus.ok ? 'text-green-400' : 'text-red-400'">
            <Wifi v-if="connStatus.ok" :size="11" /><WifiOff v-else :size="11" />
            {{ connStatus.ok ? 'Connected' : 'Unreachable' }}
          </span>
        </div>
      </SettingGroup>

      <SettingGroup label="Models">
        <SettingRow :icon="Sparkles" label="Chat model" description="Used for suggestions, summaries, and prompts.">
          <select v-model="appSettings.ai.ollama_model" class="settings-select max-w-44">
            <option v-for="m in ollamaModels" :key="m.name" :value="m.name">
              {{ m.name }} {{ m.size ? `(${formatModelSize(m.size)})` : '' }}
            </option>
            <option v-if="!ollamaModels.some(m => m.name === appSettings!.ai.ollama_model)" :value="appSettings.ai.ollama_model">
              {{ appSettings.ai.ollama_model }} (current)
            </option>
          </select>
        </SettingRow>
        <SettingRow :icon="Eye" label="Embedding model" description="Powers semantic search and similar-entry lookup.">
          <input v-model="appSettings.ai.ollama_embed_model" list="embed-models" placeholder="nomic-embed-text" class="settings-input w-44" />
          <datalist id="embed-models">
            <option v-for="m in availableEmbedModels" :key="m" :value="m" />
          </datalist>
        </SettingRow>
      </SettingGroup>

      <SettingGroup label="Features">
        <div v-for="f in featureToggles" :key="f.key" class="flex items-start justify-between gap-3 py-1">
          <div class="flex-1 min-w-0">
            <div class="text-[12px] text-text-secondary flex items-center gap-1.5">
              {{ f.label }}
              <span v-if="f.needsEmbed" class="text-[9px] px-1 py-px rounded bg-accent/15 text-accent">needs embed</span>
            </div>
            <p class="text-[10.5px] text-text-muted leading-snug mt-0.5">{{ f.desc }}</p>
          </div>
          <ToggleSwitch v-model="(appSettings.ai as any)[f.key]" />
        </div>
      </SettingGroup>

      <!-- Save (dirty-aware) -->
      <div class="flex items-center gap-2 pt-1">
        <SButton variant="primary" :disabled="aiSaving || !aiDirty" @click="saveAISettings">
          <Loader v-if="aiSaving" :size="12" class="animate-spin" /> Save AI Settings
        </SButton>
        <span v-if="aiDirty" class="text-[10.5px] text-amber-500">Unsaved changes</span>
      </div>

      <SettingGroup label="Download">
        <SettingRow :icon="DownloadIcon" label="Pull new model" description="Download a model into your local Ollama.">
          <div class="flex items-center gap-1.5">
            <input v-model="pullModelName" placeholder="e.g. llama3.2:3b" class="settings-input w-44" />
            <SButton variant="primary" :disabled="pulling || !pullModelName.trim()" @click="handlePullModel">
              <Loader v-if="pulling" :size="12" class="animate-spin" /> Pull
            </SButton>
          </div>
        </SettingRow>
        <p v-if="pullStatus" class="text-[10.5px] text-text-muted pl-[31px]">{{ pullStatus }}</p>
      </SettingGroup>
    </template>
  </SettingsSection>

  <AccordionItem title="Themes & Insights" :icon="Brain" description="Discover patterns in your journaling">
    <div class="space-y-3">
      <SettingRow label="Analyze journaling themes over">
        <div class="flex items-center gap-1.5">
          <select v-model.number="themesMonths" class="settings-select w-24">
            <option v-for="m in [1,3,6,12,24]" :key="m" :value="m">{{ m }} month{{ m > 1 ? 's' : '' }}</option>
          </select>
          <SButton variant="primary" :disabled="themesLoading" @click="fetchThemes">
            <Loader v-if="themesLoading" :size="12" class="animate-spin" /><Sparkles v-else :size="12" /> Analyze
          </SButton>
        </div>
      </SettingRow>
      <div v-if="themes.length" class="space-y-2 max-h-60 overflow-y-auto">
        <div v-for="(t, i) in themes" :key="i" class="p-2.5 bg-surface-hover rounded-md space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-[12px] font-medium text-text-primary">{{ t.theme }}</span>
            <span class="text-[11px] text-accent">{{ t.frequency }}</span>
          </div>
          <div v-if="t.months_mentioned.length" class="text-[10px] text-text-muted">Months: {{ t.months_mentioned.join(', ') }}</div>
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
