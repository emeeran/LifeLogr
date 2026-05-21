<script setup lang="ts">
import { ref } from 'vue'
import { grammarCheck, spellCheck, rewrite, continueWriting, aiStatus } from '../../api/ai'
import type { GrammarSuggestion } from '../../types'
import { Sparkles, SpellCheck, RefreshCw, CheckCircle, AlertCircle, Loader, Lightbulb } from 'lucide-vue-next'

const props = defineProps<{ text: string }>()
const emit = defineEmits<{ apply: [text: string] }>()

const loading = ref(false)
const result = ref('')
const suggestions = ref<GrammarSuggestion[]>([])
const mode = ref<'grammar' | 'spell' | 'rewrite' | 'continue'>('grammar')
const error = ref('')
const available = ref<boolean | null>(null)

async function checkAvailability() {
  try {
    const status = await aiStatus()
    available.value = status.ollama_available && status.model_loaded
  } catch {
    available.value = false
  }
}
checkAvailability()

async function runCheck(m: 'grammar' | 'spell' | 'rewrite' | 'continue') {
  mode.value = m
  loading.value = true
  error.value = ''
  suggestions.value = []
  result.value = ''
  try {
    if (m === 'grammar') {
      const res = await grammarCheck(props.text)
      result.value = res.corrected_text
      suggestions.value = res.suggestions
    } else if (m === 'spell') {
      const res = await spellCheck(props.text)
      result.value = res.corrected_text
      suggestions.value = res.misspellings
    } else if (m === 'rewrite') {
      const res = await rewrite(props.text, 'concise')
      result.value = res.rewritten_text
    } else if (m === 'continue') {
      const res = await continueWriting(props.text)
      result.value = res.continuation
    }
  } catch (e: any) {
    error.value = e.message || 'AI service unavailable'
  } finally {
    loading.value = false
  }
}

function retry() {
  if (mode.value) runCheck(mode.value)
}

function applyResult() {
  if (result.value) emit('apply', result.value)
}
</script>

<template>
  <div class="border border-border rounded-lg bg-surface p-3 space-y-3 text-sm">
    <div class="flex items-center justify-between">
      <span class="font-medium text-text-primary flex items-center gap-1"><Sparkles :size="14" /> AI Tools</span>
      <span v-if="available === false" class="text-xs text-red-400 flex items-center gap-1"><AlertCircle :size="12" /> Ollama offline</span>
      <span v-else-if="available === true" class="text-xs text-green-400 flex items-center gap-1"><CheckCircle :size="12" /> Ollama ready</span>
    </div>

    <div class="flex gap-2">
      <button @click="runCheck('grammar')" :disabled="loading || !props.text"
        class="px-2.5 py-1 bg-accent/10 text-accent rounded text-xs hover:bg-accent/20 disabled:opacity-50 flex items-center gap-1">
        <Loader v-if="loading && mode === 'grammar'" :size="12" class="animate-spin" />
        <SpellCheck v-else :size="12" /> Grammar
      </button>
      <button @click="runCheck('spell')" :disabled="loading || !props.text"
        class="px-2.5 py-1 bg-accent/10 text-accent rounded text-xs hover:bg-accent/20 disabled:opacity-50 flex items-center gap-1">
        <Loader v-if="loading && mode === 'spell'" :size="12" class="animate-spin" />
        <SpellCheck v-else :size="12" /> Spell
      </button>
      <button @click="runCheck('rewrite')" :disabled="loading || !props.text"
        class="px-2.5 py-1 bg-accent/10 text-accent rounded text-xs hover:bg-accent/20 disabled:opacity-50 flex items-center gap-1">
        <Loader v-if="loading && mode === 'rewrite'" :size="12" class="animate-spin" />
        <RefreshCw v-else :size="12" /> Rewrite
      </button>
      <button @click="runCheck('continue')" :disabled="loading || !props.text"
        class="px-2.5 py-1 bg-accent/10 text-accent rounded text-xs hover:bg-accent/20 disabled:opacity-50 flex items-center gap-1">
        <Loader v-if="loading && mode === 'continue'" :size="12" class="animate-spin" />
        <Lightbulb v-else :size="12" /> Continue
      </button>
    </div>

    <div v-if="error" class="text-xs text-red-400">{{ error }}</div>

    <div v-if="result" class="space-y-2">
      <div class="text-xs text-text-secondary">{{ suggestions.length }} suggestion(s)</div>
      <div class="bg-surface-hover rounded p-2 text-text-primary max-h-40 overflow-y-auto whitespace-pre-wrap">{{ result }}</div>
      <div class="flex gap-2">
        <button @click="applyResult" class="px-3 py-1 bg-accent text-white text-xs rounded hover:bg-accent/90">
          Apply
        </button>
        <button @click="retry" :disabled="loading" class="px-3 py-1 bg-surface-hover text-text-secondary text-xs rounded hover:text-text-primary flex items-center gap-1 disabled:opacity-50">
          <RefreshCw :size="11" /> Retry
        </button>
      </div>
    </div>
  </div>
</template>
