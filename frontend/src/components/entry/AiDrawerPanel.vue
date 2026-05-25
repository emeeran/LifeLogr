<script setup lang="ts">
import { ref, watch } from 'vue'
import { grammarCheck, spellCheck, rewrite, continueWriting, aiStatus, runEntryAnalysis, getEntryAnalysis, findSimilar, summarize, expand, changeTone, translate } from '../../api/ai'
import type { GrammarSuggestion, EntryAnalysisResponse, SimilarEntry } from '../../types'
import {
  SpellCheck, RefreshCw, CheckCircle, AlertCircle, Loader,
  BarChart3, Sparkles, Wand2, Type, Eraser, X, ChevronRight,
  TrendingUp, MessageSquare, History, Layers, FileText, Maximize2,
  MessageCircle, Globe
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
const mode = ref<'grammar' | 'spell' | 'rewrite' | 'continue' | 'summarize' | 'expand' | 'change-tone' | 'translate'>('grammar')
const error = ref('')
const available = ref<boolean | null>(null)
const activeTab = ref<'tools' | 'analysis'>('tools')

// Change tone picker
const selectedTone = ref('formal')
const tones = ['formal', 'casual', 'friendly', 'professional', 'empathetic', 'humorous']

// Translate picker
const selectedLanguage = ref('spanish')
const languages = ['english', 'spanish', 'french', 'german', 'portuguese', 'japanese', 'korean', 'chinese', 'arabic', 'hindi']

// Tool history (localStorage)
interface ToolHistoryItem {
  tool: string
  timestamp: number
  preview: string
}
const toolHistory = ref<ToolHistoryItem[]>([])
try {
  const stored = localStorage.getItem('diarium-ai-tool-history')
  if (stored) toolHistory.value = JSON.parse(stored)
} catch { /* ignore */ }

function addToHistory(tool: string, text: string) {
  toolHistory.value.unshift({
    tool,
    timestamp: Date.now(),
    preview: text.slice(0, 80) + (text.length > 80 ? '...' : ''),
  })
  if (toolHistory.value.length > 20) toolHistory.value.pop()
  localStorage.setItem('diarium-ai-tool-history', JSON.stringify(toolHistory.value))
}

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
  if (!text && m !== 'summarize') {
    error.value = 'Please select some text in the editor first.'
    return
  }

  mode.value = m
  loading.value = true
  error.value = ''
  suggestions.value = []
  result.value = ''
  originalText.value = text

  try {
    if (m === 'grammar') {
      const res = await grammarCheck(text)
      result.value = res.corrected_text
      suggestions.value = res.suggestions
    } else if (m === 'spell') {
      const res = await spellCheck(text)
      result.value = res.corrected_text
      suggestions.value = res.misspellings
    } else if (m === 'rewrite') {
      const res = await rewrite(text, 'formal')
      result.value = res.rewritten_text
    } else if (m === 'continue') {
      const res = await continueWriting(text)
      result.value = res.continuation
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
    }
    if (result.value) addToHistory(m, result.value)
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
}

// ── Analysis ──
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
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-hover/30">
      <div class="flex items-center gap-2">
        <Sparkles :size="16" class="text-accent" />
        <span class="text-sm font-semibold text-text-primary">AI Smart Actions</span>
      </div>
      <button @click="emit('close')" class="p-1 hover:bg-surface-hover rounded transition-colors text-text-muted">
        <X :size="16" />
      </button>
    </div>

    <!-- Status & Tabs -->
    <div class="px-4 py-2 border-b border-border space-y-2">
      <div class="flex items-center justify-between">
        <span v-if="available === false" class="text-[10px] text-red-400 flex items-center gap-1">
          <AlertCircle :size="11" /> Ollama offline
        </span>
        <span v-else-if="available === true" class="text-[10px] text-green-400 flex items-center gap-1">
          <CheckCircle :size="11" /> AI Engine Ready
        </span>
        <span v-else class="text-[10px] text-text-muted animate-pulse">Initializing engine...</span>

        <div class="flex bg-surface-hover rounded-md p-0.5">
          <button
            @click="activeTab = 'tools'"
            class="px-3 py-1 text-[10px] font-medium rounded transition-all"
            :class="activeTab === 'tools' ? 'bg-surface shadow-sm text-accent' : 'text-text-muted hover:text-text-secondary'"
          >Tools</button>
          <button
            @click="activeTab = 'analysis'"
            :disabled="!hasEntry"
            class="px-3 py-1 text-[10px] font-medium rounded transition-all disabled:opacity-30"
            :class="activeTab === 'analysis' ? 'bg-surface shadow-sm text-accent' : 'text-text-muted hover:text-text-secondary'"
          >Analysis</button>
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <!-- TOOLS TAB -->
      <div v-if="activeTab === 'tools'" class="p-4 space-y-4">
        <!-- Action Menu -->
        <div class="space-y-1">
          <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">Selection Tools</div>
          <div class="grid grid-cols-1 gap-1">
            <button @click="runCheck('grammar')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><SpellCheck :size="14" /> Fix Grammar</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button @click="runCheck('spell')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><Type :size="14" /> Fix Spelling</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button @click="runCheck('rewrite')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><RefreshCw :size="14" /> Polished Rewrite</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button @click="runCheck('continue')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><Wand2 :size="14" /> Continue Writing</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
          </div>
        </div>

        <!-- Smart Tools Section -->
        <div class="space-y-1">
          <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">Smart Tools</div>
          <div class="grid grid-cols-1 gap-1">
            <button @click="runCheck('summarize')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><FileText :size="14" /> Summarize</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button @click="runCheck('expand')" :disabled="loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
              <div class="flex items-center gap-2"><Maximize2 :size="14" /> Expand & Elaborate</div>
              <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>

            <!-- Change Tone with picker -->
            <div class="space-y-1">
              <div class="flex gap-1 flex-wrap px-3">
                <button v-for="t in tones" :key="t" @click="selectedTone = t"
                  class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer transition-colors"
                  :class="selectedTone === t ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
                >{{ t }}</button>
              </div>
              <button @click="runCheck('change-tone')" :disabled="loading"
                class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
                <div class="flex items-center gap-2"><MessageCircle :size="14" /> Change Tone ({{ selectedTone }})</div>
                <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            </div>

            <!-- Translate with picker -->
            <div class="space-y-1">
              <div class="flex gap-1 flex-wrap px-3">
                <button v-for="l in languages" :key="l" @click="selectedLanguage = l"
                  class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer transition-colors"
                  :class="selectedLanguage === l ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
                >{{ l }}</button>
              </div>
              <button @click="runCheck('translate')" :disabled="loading"
                class="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all group text-xs text-text-secondary">
                <div class="flex items-center gap-2"><Globe :size="14" /> Translate to {{ selectedLanguage }}</div>
                <ChevronRight :size="12" class="opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            </div>
          </div>
        </div>

        <!-- Processing State -->
        <div v-if="loading" class="flex flex-col items-center justify-center py-8 space-y-3">
          <Loader :size="24" class="text-accent animate-spin" />
          <span class="text-[11px] text-text-muted">AI is thinking...</span>
        </div>

        <!-- Error State -->
        <div v-if="error" class="p-3 bg-red-400/10 border border-red-400/20 rounded-lg flex items-start gap-2">
          <AlertCircle :size="14" class="text-red-400 shrink-0 mt-0.5" />
          <span class="text-[11px] text-red-400 leading-tight">{{ error }}</span>
        </div>

        <!-- Result Comparison -->
        <div v-if="result" class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider">Result</div>
            <button @click="clearResult" class="p-1 hover:bg-surface-hover rounded transition-colors text-text-muted">
              <Eraser :size="12" />
            </button>
          </div>

          <div class="space-y-2">
            <div class="p-3 rounded-lg bg-surface-hover border border-border">
              <div class="text-[9px] text-text-muted uppercase font-bold mb-1 opacity-50">Original Selection</div>
              <div class="text-[11px] text-text-secondary line-through opacity-60 italic whitespace-pre-wrap">{{ originalText }}</div>
            </div>

            <div class="p-3 rounded-lg bg-accent/5 border border-accent/20">
              <div class="text-[9px] text-accent uppercase font-bold mb-1">AI Improvement</div>
              <div class="text-[11px] text-text-primary whitespace-pre-wrap">{{ result }}</div>
            </div>
          </div>

          <div class="flex gap-2 pt-2">
            <button
              @click="applyResult"
              class="flex-1 py-2 bg-accent text-white rounded-lg text-xs font-medium hover:bg-accent-hover transition-colors shadow-lg shadow-accent/20"
            >Replace Selection</button>
            <button
              @click="clearResult"
              class="px-4 py-2 bg-surface-hover text-text-secondary rounded-lg text-xs font-medium hover:text-text-primary transition-colors"
            >Discard</button>
          </div>
        </div>

        <!-- Tool History -->
        <div v-if="toolHistory.length && !result && !loading" class="space-y-1.5">
          <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider">Recent Tools</div>
          <div class="space-y-1">
            <div v-for="(h, i) in toolHistory.slice(0, 5)" :key="i"
              class="px-2 py-1.5 bg-surface-hover/30 rounded text-[10px] border border-border/30">
              <div class="flex items-center gap-1 mb-0.5">
                <span class="font-medium text-text-secondary">{{ h.tool }}</span>
                <span class="text-text-muted ml-auto">{{ new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</span>
              </div>
              <div class="text-text-muted truncate">{{ h.preview }}</div>
            </div>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="!loading && !result && !error && !toolHistory.length" class="flex flex-col items-center justify-center py-12 text-center space-y-3 opacity-40">
          <Wand2 :size="32" class="text-text-muted" />
          <div class="text-xs text-text-muted leading-tight">
            Select text in the editor<br>and choose a smart action.
          </div>
        </div>
      </div>

      <!-- ANALYSIS TAB -->
      <div v-if="activeTab === 'analysis'" class="p-4 space-y-5">
        <div class="flex items-center justify-between">
          <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
            <TrendingUp :size="12" /> Intelligence
          </div>
          <button
            @click="runAnalysis"
            :disabled="analysisLoading"
            class="flex items-center gap-1 px-3 py-1 rounded-full text-[10px] bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 transition-colors"
          >
            <Loader v-if="analysisLoading" :size="10" class="animate-spin" />
            <RefreshCw v-else :size="10" />
            {{ analysis ? 'Re-analyze' : 'Analyze Entry' }}
          </button>
        </div>

        <div v-if="analysisLoading && !analysis" class="flex flex-col items-center justify-center py-12 space-y-3">
          <Loader :size="24" class="text-accent animate-spin" />
          <span class="text-[11px] text-text-muted">Analyzing sentiment & themes...</span>
        </div>

        <div v-else-if="analysis" class="space-y-6">
          <!-- Sentiment -->
          <div class="space-y-2">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider">Sentiment & Mood</div>
            <div v-if="analysis.sentiment" class="p-3 bg-surface-hover/50 rounded-xl border border-border/50">
              <div class="flex items-center justify-between mb-3">
                <span class="text-sm font-semibold text-text-primary capitalize">{{ analysis.sentiment.primary_emotion }}</span>
                <span class="text-[10px] font-bold text-accent px-2 py-0.5 bg-accent/10 rounded-full">{{ analysis.sentiment.intensity }}/10</span>
              </div>
              <div class="space-y-1">
                <div class="flex justify-between text-[9px] text-text-muted mb-1">
                  <span>Negative</span>
                  <span>Positive</span>
                </div>
                <div class="h-2 bg-surface rounded-full overflow-hidden border border-border/30">
                  <div class="h-full rounded-full transition-all duration-1000"
                    :class="analysis.sentiment.valence >= 0 ? 'bg-green-400' : 'bg-red-400'"
                    :style="{ marginLeft: (analysis.sentiment.valence >= 0 ? '50%' : (50 + analysis.sentiment.valence * 50) + '%'), width: Math.abs(analysis.sentiment.valence * 50) + '%' }" />
                </div>
              </div>
            </div>
          </div>

          <!-- Summary -->
          <div class="space-y-2">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Layers :size="12" /> Executive Summary
            </div>
            <div class="p-3 bg-accent/5 rounded-xl border border-accent/10 text-[11px] text-text-primary leading-relaxed">
              {{ analysis.summary }}
            </div>
          </div>

          <!-- Reflection -->
          <div class="space-y-2">
            <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
              <MessageSquare :size="12" /> Reflection Prompts
            </div>
            <div class="space-y-2">
              <div
                v-for="(p, i) in analysis.reflection_prompts"
                :key="i"
                class="p-3 bg-surface-hover/30 rounded-lg text-[11px] text-text-secondary border-l-2 border-accent/30 italic"
              >
                "{{ p }}"
              </div>
            </div>
          </div>

          <!-- Similar -->
          <div class="space-y-2 pt-2">
            <div class="flex items-center justify-between">
              <div class="text-[10px] font-bold text-text-muted uppercase tracking-wider flex items-center gap-1">
                <History :size="12" /> Similar Moments
              </div>
              <button @click="fetchSimilar" :disabled="similarLoading" class="text-[10px] text-accent hover:underline">
                {{ similarLoading ? 'Searching...' : 'Search' }}
              </button>
            </div>
            <div class="space-y-1.5">
              <div v-for="s in similarEntries" :key="s.id"
                class="flex items-center justify-between p-2 bg-surface-hover/50 rounded-lg border border-border/50 hover:border-accent/30 cursor-pointer transition-colors">
                <div>
                  <div class="text-[11px] font-medium text-text-primary">{{ s.title || 'Untitled' }}</div>
                  <div class="text-[9px] text-text-muted">{{ s.entry_date }}</div>
                </div>
                <div class="text-[10px] font-bold text-accent bg-accent/5 px-2 py-0.5 rounded-full">
                  {{ (s.similarity_score * 100).toFixed(0) }}%
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-12 text-center space-y-4 opacity-40">
          <BarChart3 :size="32" class="text-text-muted" />
          <div class="text-xs text-text-muted leading-tight">
            Analyze your entry to discover<br>emotions, summaries and patterns.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
