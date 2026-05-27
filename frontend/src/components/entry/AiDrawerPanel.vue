<script setup lang="ts">
import { ref, watch } from 'vue'
import { grammarCheck, rewrite, aiStatus, runEntryAnalysis, getEntryAnalysis, findSimilar, summarize, expand, changeTone, translate, analyzeText, defineText } from '../../api/ai'
import type { GrammarSuggestion, EntryAnalysisResponse, SimilarEntry } from '../../types'
import { AI_TONE_OPTIONS, AI_TRANSLATE_LANGUAGES } from '../../composables/useAiTools'
import {
  RefreshCw, CheckCircle, AlertCircle, Loader,
  BarChart3, Sparkles, Wand2, Type, Eraser,
  TrendingUp, MessageSquare, Layers, FileText, Maximize2,
  MessageCircle, Globe, Copy, Check, Search, BookOpen
} from 'lucide-vue-next'

const props = defineProps<{
  getSelection: () => string
  applyText: (text: string) => void
  hasEntry: boolean
  entryId: number | null
}>()

const emit = defineEmits<{ close: [] }>()

// ── AI Tools ──
const loading = ref(false)
const result = ref('')
const originalText = ref('')
const suggestions = ref<GrammarSuggestion[]>([])
const mode = ref<'grammar-spelling' | 'rewrite' | 'summarize' | 'expand' | 'change-tone' | 'translate' | 'analysis' | 'define'>('grammar-spelling')
const error = ref('')
const available = ref<boolean | null>(null)
const activeTab = ref<'tools' | 'analysis'>('tools')

// Change tone picker
const selectedTone = ref('formal')
const tones = AI_TONE_OPTIONS.map(t => t as string)

// Translate picker
const selectedLanguage = ref('tamil')
const languages = AI_TRANSLATE_LANGUAGES

// Analysis result (for the analysis tool)
const analysisResult = ref<{ emotions: string[]; themes: string[]; summary: string } | null>(null)

async function checkAvailability() {
  try {
    const status = await aiStatus()
    available.value = status.ollama_available && status.model_loaded
  } catch {
    available.value = false
  }
}
checkAvailability()

async function runCheck(m: typeof mode.value) {
  const text = props.getSelection()
  if (!text) {
    error.value = 'Please select some text in the editor first.'
    return
  }

  mode.value = m
  loading.value = true
  error.value = ''
  suggestions.value = []
  result.value = ''
  originalText.value = text
  analysisResult.value = null

  try {
    if (m === 'grammar-spelling') {
      const res = await grammarCheck(text)
      result.value = res.corrected_text
      suggestions.value = res.suggestions
    } else if (m === 'rewrite') {
      const res = await rewrite(text, 'formal')
      result.value = res.rewritten_text
    } else if (m === 'summarize') {
      const res = await summarize(text)
      result.value = res.summary
    } else if (m === 'expand') {
      const res = await expand(text)
      result.value = res.expanded_text
    } else if (m === 'change-tone') {
      const res = await changeTone(text, selectedTone.value)
      result.value = res.changed_text
    } else if (m === 'translate') {
      const res = await translate(text, selectedLanguage.value)
      result.value = res.translated_text
    } else if (m === 'analysis') {
      const res = await analyzeText(text)
      analysisResult.value = res
      const emotionStr = res.emotions.length ? res.emotions.join(', ') : 'None detected'
      const themeStr = res.themes.length ? res.themes.join(', ') : 'None detected'
      result.value = `Emotions: ${emotionStr}\nThemes: ${themeStr}\n\nSummary: ${res.summary}`
    } else if (m === 'define') {
      const res = await defineText(text)
      result.value = res.definition
    }
  } catch (e: any) {
    error.value = e.message || 'AI service unavailable'
  } finally {
    loading.value = false
  }
}

function applyResult() {
  if (result.value) {
    props.applyText(result.value)
    result.value = ''
    originalText.value = ''
  }
}

function clearResult() {
  result.value = ''
  originalText.value = ''
  error.value = ''
  analysisResult.value = null
}

const copied = ref(false)
function copyResult() {
  if (!result.value) return
  navigator.clipboard.writeText(result.value).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  })
}

// ── Entry Analysis ──
const analysis = ref<EntryAnalysisResponse | null>(null)
const analysisLoading = ref(false)
const similarEntries = ref<SimilarEntry[]>([])
const similarLoading = ref(false)

async function runAnalysis() {
  if (!props.hasEntry || !props.entryId) return
  analysisLoading.value = true
  analysis.value = null
  similarEntries.value = []
  try {
    analysis.value = await runEntryAnalysis(props.entryId)
  } catch { /* ignore */ }
  finally { analysisLoading.value = false }
}

async function loadAnalysis() {
  if (!props.hasEntry || !props.entryId) return
  analysisLoading.value = true
  try {
    analysis.value = await getEntryAnalysis(props.entryId)
  } catch { /* ignore */ }
  finally { analysisLoading.value = false }
}

async function fetchSimilar() {
  if (!props.entryId) return
  similarLoading.value = true
  try {
    const res = await findSimilar(props.entryId)
    similarEntries.value = res.similar
  } catch { /* ignore */ }
  finally { similarLoading.value = false }
}

// Auto-load analysis if it exists when switching to analysis tab
watch(activeTab, (newTab) => {
  if (newTab === 'analysis' && !analysis.value && props.hasEntry) {
    loadAnalysis()
  }
})
</script>

<template>
  <div class="flex flex-col h-full bg-surface">
    <!-- Status & Tabs -->
    <div class="px-3 py-2 border-b border-border space-y-1.5">
      <div class="flex items-center justify-between">
        <span v-if="available === false" class="text-[10px] text-red-400 flex items-center gap-1">
          <AlertCircle :size="11" /> Offline
        </span>
        <span v-else-if="available === true" class="text-[10px] text-green-400 flex items-center gap-1">
          <CheckCircle :size="11" /> Ready
        </span>
        <span v-else class="text-[10px] text-text-muted animate-pulse">...</span>

        <div class="flex bg-surface-hover rounded-md p-0.5">
          <button
            @click="activeTab = 'tools'"
            class="px-2.5 py-0.5 text-[10px] font-medium rounded transition-all"
            :class="activeTab === 'tools' ? 'bg-surface shadow-sm text-accent' : 'text-text-muted hover:text-text-secondary'"
          >Tools</button>
          <button
            @click="activeTab = 'analysis'"
            :disabled="!hasEntry"
            class="px-2.5 py-0.5 text-[10px] font-medium rounded transition-all disabled:opacity-30"
            :class="activeTab === 'analysis' ? 'bg-surface shadow-sm text-accent' : 'text-text-muted hover:text-text-secondary'"
          >Analysis</button>
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <!-- TOOLS TAB -->
      <div v-if="activeTab === 'tools'" class="p-3 space-y-3">
        <!-- Compact 2-column tool grid -->
        <div class="grid grid-cols-2 gap-1">
          <button @click="runCheck('grammar-spelling')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <Type :size="12" /> Grammar
          </button>
          <button @click="runCheck('rewrite')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <Wand2 :size="12" /> Rewrite
          </button>
          <button @click="runCheck('summarize')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <FileText :size="12" /> Summarize
          </button>
          <button @click="runCheck('expand')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <Maximize2 :size="12" /> Expand
          </button>
          <button @click="runCheck('analysis')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <Search :size="12" /> Analysis
          </button>
          <button @click="runCheck('change-tone')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <MessageCircle :size="12" /> Tone
          </button>
          <button @click="runCheck('define')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <BookOpen :size="12" /> Define
          </button>
        </div>

        <!-- Tone pills (compact) -->
        <div class="flex gap-1 flex-wrap">
          <button v-for="t in tones" :key="t" @click="selectedTone = t"
            class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer transition-colors"
            :class="selectedTone === t ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
          >{{ t }}</button>
        </div>

        <!-- Language pills (compact) -->
        <div class="flex gap-1 flex-wrap">
          <button v-for="l in languages" :key="l" @click="selectedLanguage = l"
            class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer transition-colors"
            :class="selectedLanguage === l ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
          >{{ l }}</button>
        </div>

        <!-- Translate button (uses language picker above) -->
        <button @click="runCheck('translate')" :disabled="loading"
          class="w-full flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
          <Globe :size="12" /> Translate ({{ selectedLanguage }})
        </button>

        <!-- Processing State -->
        <div v-if="loading" class="flex flex-col items-center justify-center py-4 space-y-2">
          <Loader :size="20" class="text-accent animate-spin" />
          <span class="text-[10px] text-text-muted">Thinking...</span>
        </div>

        <!-- Error State -->
        <div v-if="error" class="p-2 bg-red-400/10 border border-red-400/20 rounded flex items-start gap-1.5">
          <AlertCircle :size="12" class="text-red-400 shrink-0 mt-0.5" />
          <span class="text-[10px] text-red-400 leading-tight">{{ error }}</span>
        </div>

        <!-- Result -->
        <div v-if="result" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-bold text-text-muted uppercase tracking-wider">Result</span>
            <button @click="clearResult" class="p-0.5 hover:bg-surface-hover rounded transition-colors text-text-muted">
              <Eraser :size="11" />
            </button>
          </div>

          <div class="space-y-1.5">
            <div class="p-2 rounded bg-surface-hover border border-border">
              <div class="text-[9px] text-text-muted uppercase font-bold mb-0.5 opacity-50">Original</div>
              <div class="text-[10px] text-text-secondary line-through opacity-60 italic whitespace-pre-wrap">{{ originalText }}</div>
            </div>

            <div class="p-2 rounded bg-accent/5 border border-accent/20">
              <div class="text-[9px] text-accent uppercase font-bold mb-0.5">AI Result</div>
              <div class="text-[10px] text-text-primary whitespace-pre-wrap">{{ result }}</div>
            </div>
          </div>

          <!-- Analysis breakdown (when mode is analysis) -->
          <div v-if="mode === 'analysis' && analysisResult" class="space-y-1.5">
            <div v-if="analysisResult.emotions.length" class="p-2 rounded bg-surface-hover/50 border border-border/50">
              <div class="text-[9px] text-text-muted uppercase font-bold mb-0.5">Emotions</div>
              <div class="flex flex-wrap gap-1">
                <span v-for="e in analysisResult.emotions" :key="e"
                  class="px-1.5 py-0.5 rounded-full text-[9px] bg-accent/15 text-accent">{{ e }}</span>
              </div>
            </div>
            <div v-if="analysisResult.themes.length" class="p-2 rounded bg-surface-hover/50 border border-border/50">
              <div class="text-[9px] text-text-muted uppercase font-bold mb-0.5">Themes</div>
              <div class="flex flex-wrap gap-1">
                <span v-for="t in analysisResult.themes" :key="t"
                  class="px-1.5 py-0.5 rounded-full text-[9px] bg-surface-hover text-text-secondary">{{ t }}</span>
              </div>
            </div>
          </div>

          <div class="flex gap-1.5">
            <button
              @click="applyResult"
              class="flex-1 py-1.5 bg-accent text-white rounded text-[10px] font-medium hover:bg-accent-hover transition-colors"
            >Replace</button>
            <button
              @click="copyResult"
              class="px-2.5 py-1.5 bg-surface-hover text-text-secondary rounded text-[10px] font-medium hover:text-text-primary transition-colors flex items-center gap-0.5"
            >
              <Check v-if="copied" :size="10" class="text-green-400" />
              <Copy v-else :size="10" />
              {{ copied ? 'Done' : 'Copy' }}
            </button>
            <button
              @click="clearResult"
              class="px-2.5 py-1.5 bg-surface-hover text-text-secondary rounded text-[10px] font-medium hover:text-text-primary transition-colors"
            >Discard</button>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="!loading && !result && !error" class="flex flex-col items-center justify-center py-8 text-center space-y-2 opacity-40">
          <Sparkles :size="24" class="text-text-muted" />
          <div class="text-[10px] text-text-muted leading-tight">
            Select text and choose a tool.
          </div>
        </div>
      </div>

      <!-- ANALYSIS TAB -->
      <div v-if="activeTab === 'analysis'" class="p-3 space-y-4">
        <div class="flex items-center justify-between">
          <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
            <TrendingUp :size="11" /> Intelligence
          </div>
          <button
            @click="runAnalysis"
            :disabled="analysisLoading"
            class="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 transition-colors"
          >
            <Loader v-if="analysisLoading" :size="9" class="animate-spin" />
            <RefreshCw v-else :size="9" />
            {{ analysis ? 'Re-analyze' : 'Analyze' }}
          </button>
        </div>

        <div v-if="analysisLoading && !analysis" class="flex flex-col items-center justify-center py-8 space-y-2">
          <Loader :size="20" class="text-accent animate-spin" />
          <span class="text-[10px] text-text-muted">Analyzing...</span>
        </div>

        <div v-else-if="analysis" class="space-y-4">
          <!-- Sentiment -->
          <div class="space-y-1.5">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider">Sentiment</div>
            <div v-if="analysis.sentiment" class="p-2 bg-surface-hover/50 rounded-lg border border-border/50">
              <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-semibold text-text-primary capitalize">{{ analysis.sentiment.primary_emotion }}</span>
                <span class="text-[9px] font-bold text-accent px-1.5 py-0.5 bg-accent/10 rounded-full">{{ analysis.sentiment.intensity }}/10</span>
              </div>
              <div class="space-y-0.5">
                <div class="flex justify-between text-[8px] text-text-muted mb-0.5">
                  <span>Negative</span>
                  <span>Positive</span>
                </div>
                <div class="h-1.5 bg-surface rounded-full overflow-hidden border border-border/30">
                  <div class="h-full rounded-full transition-all duration-1000"
                    :class="analysis.sentiment.valence >= 0 ? 'bg-green-400' : 'bg-red-400'"
                    :style="{ marginLeft: (analysis.sentiment.valence >= 0 ? '50%' : (50 + analysis.sentiment.valence * 50) + '%'), width: Math.abs(analysis.sentiment.valence * 50) + '%' }" />
                </div>
              </div>
            </div>
          </div>

          <!-- Summary -->
          <div class="space-y-1.5">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Layers :size="11" /> Summary
            </div>
            <div class="p-2 bg-accent/5 rounded-lg border border-accent/10 text-[10px] text-text-primary leading-relaxed">
              {{ analysis.summary }}
            </div>
          </div>

          <!-- Reflection -->
          <div class="space-y-1.5">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
              <MessageSquare :size="11" /> Reflection
            </div>
            <div class="space-y-1">
              <div
                v-for="(p, i) in analysis.reflection_prompts"
                :key="i"
                class="p-2 bg-surface-hover/30 rounded text-[10px] text-text-secondary border-l-2 border-accent/30 italic"
              >
                "{{ p }}"
              </div>
            </div>
          </div>

          <!-- Similar -->
          <div class="space-y-1.5 pt-1">
            <div class="flex items-center justify-between">
              <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
                <BarChart3 :size="11" /> Similar
              </div>
              <button @click="fetchSimilar" :disabled="similarLoading" class="text-[9px] text-accent hover:underline">
                {{ similarLoading ? '...' : 'Search' }}
              </button>
            </div>
            <div class="space-y-1">
              <div v-for="s in similarEntries" :key="s.id"
                class="flex items-center justify-between p-1.5 bg-surface-hover/50 rounded border border-border/50 hover:border-accent/30 cursor-pointer transition-colors">
                <div>
                  <div class="text-[10px] font-medium text-text-primary">{{ s.title || 'Untitled' }}</div>
                  <div class="text-[8px] text-text-muted">{{ s.entry_date }}</div>
                </div>
                <div class="text-[9px] font-bold text-accent bg-accent/5 px-1.5 py-0.5 rounded-full">
                  {{ (s.similarity_score * 100).toFixed(0) }}%
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-8 text-center space-y-2 opacity-40">
          <BarChart3 :size="24" class="text-text-muted" />
          <div class="text-[10px] text-text-muted leading-tight">
            Analyze entry to discover<br>emotions and patterns.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
