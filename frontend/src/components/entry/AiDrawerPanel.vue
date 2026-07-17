<script setup lang="ts">
import { computed, ref } from 'vue'
import { aiStatus, callAiTool } from '../../api/ai'
import { AI_TOOLS, AI_TOOL_BY_ID } from '../../composables/aiToolRegistry'
import type { GrammarSuggestion } from '../../types'
import {
  CheckCircle, AlertCircle, Loader,
  Sparkles, Eraser,
  Copy, Check,
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
const mode = ref<string>('grammar')
const error = ref('')
const available = ref<boolean | null>(null)
const selectedParam = ref<string>('formal')

const activeTool = computed(() => AI_TOOL_BY_ID[mode.value])
const paramOptions = computed(() => activeTool.value?.param?.options ?? [])
const showParamPills = computed(() => !!activeTool.value?.param)

async function checkAvailability() {
  try {
    const status = await aiStatus()
    available.value = status.ollama_available && status.model_loaded
  } catch {
    available.value = false
  }
}
checkAvailability()

async function runTool(toolId: string) {
  const def = AI_TOOL_BY_ID[toolId]
  if (!def) return
  const text = props.getSelection()
  if (!text) {
    error.value = 'Please select some text in the editor first.'
    return
  }

  mode.value = toolId
  if (def.param) selectedParam.value = def.param.default
  loading.value = true
  error.value = ''
  suggestions.value = []
  result.value = ''
  originalText.value = text

  try {
    const { text: out, suggestions: sugg } = await callAiTool(def, text, selectedParam.value)
    result.value = out
    suggestions.value = sugg
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'AI service unavailable'
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
        <!-- Compact tool grid (data-driven from the registry) -->
        <div class="grid grid-cols-2 gap-1">
          <button
            v-for="tool in AI_TOOLS"
            :key="tool.id"
            @click="runTool(tool.id)"
            :disabled="loading"
            class="flex items-center justify-center gap-1 px-2 py-1.5 rounded bg-surface-hover/50 hover:bg-accent/10 hover:text-accent transition-all text-[11px] text-text-secondary disabled:opacity-50"
          >
            <component :is="tool.icon" :size="12" /> {{ tool.label }}
          </button>
        </div>

        <!-- Parameter pills for the active tool (tone / voice / language) -->
        <div v-if="showParamPills" class="flex gap-1 flex-wrap">
          <button v-for="opt in paramOptions" :key="opt" @click="selectedParam = opt"
            class="px-1.5 py-0.5 rounded text-[9px] cursor-pointer transition-colors capitalize"
            :class="selectedParam === opt ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
          >{{ opt }}</button>
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
