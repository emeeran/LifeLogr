<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import {
  Copy, Scissors, Bold, Italic, Lock, Sparkles,
  Type, SpellCheck, Wand2, Edit3, FileText, Maximize2, MessageCircle, Globe,
  Loader, RefreshCw, GripHorizontal, X
} from 'lucide-vue-next'
import type { AiToolMode, AiToneStyle } from '../../composables/useAiTools'
import type { UseUiStore } from '../../stores/ui'

const props = defineProps<{
  visible: boolean
  position: { x: number; y: number }
  aiLoading: boolean
  aiResult: string | null
  aiResultMode: AiToolMode | null
  aiToneStyle: AiToneStyle
  ui: ReturnType<typeof import('../../stores/ui')['useUiStore']>
}>()

const toneOptions: AiToneStyle[] = ['formal', 'professional', 'casual', 'friendly', 'concise', 'poetic']

const emit = defineEmits<{
  close: []
  copy: []
  cut: []
  bold: []
  italic: []
  encrypt: []
  runAiTool: [mode: AiToolMode]
  aiResultReplace: []
  aiResultInsert: []
  aiResultRetry: []
  aiResultCopy: []
  applyToneStyle: [tone: AiToneStyle]
  closeResult: []
}>()

// ── Context menu viewport clamping ──
const menuRef = ref<HTMLElement | null>(null)
const menuTop = ref(props.position.y)

watch(() => props.visible, async (vis) => {
  if (!vis) return
  menuTop.value = props.position.y
  await nextTick()
  const el = menuRef.value
  if (!el) return
  const bottom = el.getBoundingClientRect().bottom
  const overflow = bottom - window.innerHeight + 8
  if (overflow > 0) {
    menuTop.value = Math.max(8, props.position.y - overflow)
  }
})

// ── Draggable result panel state ──
const panelPos = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })

// Position the panel at the context menu location when result appears
watch(() => props.aiResult, (val) => {
  if (val && !isDragging.value) {
    panelPos.value = { x: props.position.x, y: props.position.y }
    // Clamp to viewport
    clampToViewport()
  }
})
watch(() => props.aiLoading, (loading) => {
  if (loading && !props.aiResult && !isDragging.value) {
    panelPos.value = { x: props.position.x, y: props.position.y }
    clampToViewport()
  }
})

function clampToViewport() {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const panelW = 320
  const panelH = 250
  if (panelPos.value.x + panelW > vw) panelPos.value.x = Math.max(8, vw - panelW - 8)
  if (panelPos.value.y + panelH > vh) panelPos.value.y = Math.max(8, vh - panelH - 8)
  if (panelPos.value.x < 8) panelPos.value.x = 8
  if (panelPos.value.y < 8) panelPos.value.y = 8
}

function startDrag(e: MouseEvent) {
  isDragging.value = true
  dragOffset.value = {
    x: e.clientX - panelPos.value.x,
    y: e.clientY - panelPos.value.y,
  }
  e.preventDefault()

  const onMove = (ev: MouseEvent) => {
    panelPos.value = {
      x: Math.max(0, Math.min(window.innerWidth - 100, ev.clientX - dragOffset.value.x)),
      y: Math.max(0, Math.min(window.innerHeight - 40, ev.clientY - dragOffset.value.y)),
    }
  }
  const onUp = () => {
    isDragging.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
</script>

<template>
  <!-- Standard context menu (only when no AI loading/result) -->
  <div
    v-if="visible && !aiResult && !aiLoading"
    ref="menuRef"
    class="fixed z-[200] bg-surface border border-border rounded shadow-2xl py-1 max-h-[80vh] overflow-y-auto w-52"
    :style="{ left: position.x + 'px', top: menuTop + 'px' }"
    @click.stop
  >
    <!-- Standard context menu -->
    <button @click="emit('copy'); emit('close')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Copy :size="12" /> Copy
    </button>
    <button @click="emit('cut'); emit('close')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Scissors :size="12" /> Cut
    </button>
    <div class="h-px bg-border my-1" />
    <button @click="emit('bold'); emit('close')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Bold :size="12" /> Bold
    </button>
    <button @click="emit('italic'); emit('close')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Italic :size="12" /> Italic
    </button>
    <button @click="emit('encrypt'); emit('close')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Lock :size="12" /> Encrypt Selection
    </button>
    <div class="h-px bg-border my-1" />
    <div class="px-3 py-1 text-[10px] font-semibold text-accent uppercase tracking-wider flex items-center gap-1">
      <Sparkles :size="10" /> AI Smart Tools
    </div>
    <button @click="emit('runAiTool', 'grammar')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Type :size="12" /> Fix Grammar
    </button>
    <button @click="emit('runAiTool', 'spelling')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <SpellCheck :size="12" /> Fix Spelling
    </button>
    <button @click="emit('runAiTool', 'rewrite')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Wand2 :size="12" /> Polished Rewrite
    </button>
    <button @click="emit('runAiTool', 'continue')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Edit3 :size="12" /> Continue Writing
    </button>
    <button @click="emit('runAiTool', 'summarize')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <FileText :size="12" /> Summarize
    </button>
    <button @click="emit('runAiTool', 'expand')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Maximize2 :size="12" /> Expand & Elaborate
    </button>
    <button @click="emit('runAiTool', 'tone')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <MessageCircle :size="12" /> Change Tone
    </button>
    <button @click="emit('runAiTool', 'translate')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
      <Globe :size="12" /> Translate
    </button>
  </div>

  <!-- Floating Draggable AI Result Panel -->
  <div
    v-if="aiResult || aiLoading"
    class="fixed z-[200] bg-surface border border-border rounded-lg shadow-2xl min-w-64 max-w-[28rem] max-h-[70vh] flex flex-col select-none"
    :class="isDragging ? 'cursor-grabbing shadow-accent/10' : ''"
    :style="{ left: panelPos.x + 'px', top: panelPos.y + 'px' }"
    @click.stop
  >
    <!-- Drag handle header -->
    <div
      class="flex items-center gap-1.5 px-3 py-1.5 border-b border-border cursor-grab active:cursor-grabbing shrink-0"
      @mousedown="startDrag"
    >
      <GripHorizontal :size="12" class="text-text-muted" />
      <span class="text-[10px] font-semibold text-accent uppercase tracking-wider flex items-center gap-1">
        <Sparkles :size="10" /> {{ aiResultMode }} {{ aiLoading ? 'Running...' : 'Result' }}
      </span>
      <span class="flex-1" />
      <button
        class="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary cursor-pointer transition-colors"
        @click="emit('closeResult')"
      >
        <X :size="12" />
      </button>
    </div>

    <!-- Loading state -->
    <div v-if="aiLoading && !aiResult" class="py-8 flex flex-col items-center justify-center gap-2">
      <Loader :size="24" class="animate-spin text-accent" />
      <span class="text-[10px] text-text-muted">Generating response...</span>
    </div>

    <!-- Loading overlay on retry (old result still visible) -->
    <div v-if="aiLoading && aiResult" class="absolute inset-0 bg-surface/50 rounded-lg flex flex-col items-center justify-center gap-2 z-10">
      <Loader :size="24" class="animate-spin text-accent" />
      <span class="text-[10px] text-text-muted">Regenerating...</span>
    </div>

    <!-- Result content -->
    <div v-if="aiResult" class="flex flex-col overflow-hidden" :class="aiLoading ? 'opacity-40 pointer-events-none' : ''">
      <div class="p-3 overflow-y-auto flex-1">
        <div class="p-2 bg-editor rounded text-xs text-text-primary whitespace-pre-wrap border border-border leading-relaxed">
          {{ aiResult }}
        </div>
      </div>

      <!-- Tone selector for rewrite/tone modes -->
      <div v-if="(aiResultMode === 'tone' || aiResultMode === 'rewrite')" class="px-3 pb-1 flex flex-wrap gap-1">
        <button
          v-for="tone in toneOptions"
          :key="tone"
          @click="emit('applyToneStyle', tone)"
          class="px-1.5 py-0.5 rounded text-[9px] font-medium cursor-pointer transition-colors capitalize"
          :class="aiToneStyle === tone ? 'bg-accent/20 text-accent border border-accent/30' : 'bg-surface-hover text-text-secondary hover:text-text-primary border border-transparent'"
        >{{ tone }}</button>
      </div>

      <!-- Action buttons -->
      <div class="flex items-center gap-1 px-3 py-2 border-t border-border shrink-0">
        <button @click="emit('aiResultReplace')" class="flex-1 px-2 py-1 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover transition-colors cursor-pointer">
          Replace
        </button>
        <button @click="emit('aiResultInsert')" class="flex-1 px-2 py-1 rounded text-[10px] font-medium bg-surface-hover text-text-primary hover:bg-border transition-colors cursor-pointer">
          Insert
        </button>
        <button @click="emit('aiResultRetry')" class="flex-1 px-2 py-1 rounded text-[10px] font-medium bg-surface-hover text-text-primary hover:bg-border transition-colors cursor-pointer flex items-center justify-center gap-0.5">
          <RefreshCw :size="9" /> Retry
        </button>
        <button @click="emit('aiResultCopy')" class="flex-1 px-2 py-1 rounded text-[10px] font-medium bg-surface-hover text-text-primary hover:bg-border transition-colors cursor-pointer flex items-center justify-center gap-0.5">
          <Copy :size="9" /> Copy
        </button>
      </div>
    </div>
  </div>
</template>
