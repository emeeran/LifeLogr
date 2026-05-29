<script setup lang="ts">
import { ref } from 'vue'
import { grammarCheck, rewrite, aiStatus, expand, changeTone, defineText } from '../../api/ai'
import type { GrammarSuggestion } from '../../types'
import { AI_TONE_OPTIONS } from '../../composables/useAiTools'
import {
  CheckCircle, AlertCircle, Loader,
  Sparkles, Wand2, Type, Eraser,
  Maximize2,
  MessageCircle, Copy, Check, BookOpen
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
const mode = ref<'grammar-spelling' | 'rewrite' | 'expand' | 'change-tone' | 'define'>('grammar-spelling')
const error = ref('')
const available = ref<boolean | null>(null)

// Change tone picker
const selectedTone = ref('formal')
const tones = AI_TONE_OPTIONS.map(t => t as string)

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

  try {
    if (m === 'grammar-spelling') {
      const res = await grammarCheck(text)
      result.value = res.corrected_text
      suggestions.value = res.suggestions
    } else if (m === 'rewrite') {
      const res = await rewrite(text, 'formal')
      result.value = res.rewritten_text
    } else if (m === 'expand') {
      const res = await expand(text)
      result.value = res.expanded_text
    } else if (m === 'change-tone') {
      const res = await changeTone(text, selectedTone.value)
      result.value = res.changed_text
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
}

const copied = ref(false)
function copyResult() {
  if (!result.value) return
  navigator.clipboard.writeText(result.value).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  })
}
</script>

<template>
  <div class="flex flex-col h-full bg-surface">
    <!-- Status -->
    <div class="px-3 py-2 border-b border-border space-y-1.5">
      <div class="flex items-center justify-between">
        <span v-if="available === false" class="text-[10px] text-red-400 flex items-center gap-1">
          <AlertCircle :size="11" /> Offline
        </span>
        <span v-else-if="available === true" class="text-[10px] text-green-400 flex items-center gap-1">
          <CheckCircle :size="11" /> Ready
        </span>
        <span v-else class="text-[10px] text-text-muted animate-pulse">...</span>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <div class="p-3 space-y-3">
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
          <button @click="runCheck('expand')" :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50">
            <Maximize2 :size="12" /> Expand
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
    </div>
  </div>
</template>
