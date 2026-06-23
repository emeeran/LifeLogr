<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import {
  Copy, Scissors, Bold, Italic, Lock, Sparkles, Unlock,
  ChevronRight, Loader, RefreshCw, GripHorizontal, X
} from 'lucide-vue-next'
import { AI_TOOLS, AI_TOOL_BY_ID } from '../../composables/aiToolRegistry'

const props = defineProps<{
  visible: boolean
  position: { x: number; y: number }
  aiLoading: boolean
  aiResult: string | null
  aiResultMode: string | null
  aiParamValue: string
  selectedText: string
}>()

const activeTool = computed(() =>
  props.aiResultMode ? AI_TOOL_BY_ID[props.aiResultMode] : undefined,
)
const paramOptions = computed(() => activeTool.value?.param?.options ?? [])

const emit = defineEmits<{
  close: []
  copy: []
  cut: []
  bold: []
  italic: []
  encrypt: []
  runAiTool: [mode: string]
  openAiDrawer: []
  aiResultReplace: []
  aiResultInsert: []
  aiResultRetry: []
  aiResultCopy: []
  applyToolParam: [value: string]
  closeResult: []
}>()

const isEncrypted = (text: string) => /^<!--ENC\{.+\}-->$/s.test(text.trim())
const encryptLabel = (text: string) => isEncrypted(text) ? 'Decrypt Selection' : 'Encrypt/Decrypt'

// ── AI submenu (fixed-positioned to avoid clipping) ──
const showAiSubmenu = ref(false)
const submenuPos = ref({ x: 0, y: 0 })
const aiTriggerRef = ref<HTMLElement | null>(null)

function openAiSubmenu() {
  showAiSubmenu.value = true
  nextTick(() => {
    const trigger = aiTriggerRef.value
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const submenuW = 210
    const submenuH = 240
    // Default: right side of trigger
    let x = rect.right + 2
    let y = rect.top
    // If overflows right edge, open to the left
    if (x + submenuW > window.innerWidth - 8) x = rect.left - submenuW - 2
    // If overflows bottom, shift up
    if (y + submenuH > window.innerHeight - 8) y = Math.max(8, window.innerHeight - submenuH - 8)
    submenuPos.value = { x, y }
  })
}

function closeSubmenu() {
  showAiSubmenu.value = false
}

// ── Context menu viewport clamping ──
const menuRef = ref<HTMLElement | null>(null)
const menuTop = ref(props.position.y)

watch(() => props.visible, async (vis) => {
  if (!vis) return
  showAiSubmenu.value = false
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

watch(() => props.aiResult, (val) => {
  if (val && !isDragging.value) {
    panelPos.value = { x: props.position.x, y: props.position.y }
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
      <Lock v-if="!isEncrypted(selectedText)" :size="12" />
      <Unlock v-else :size="12" />
      {{ encryptLabel(selectedText) }}
    </button>
    <div class="h-px bg-border my-1" />
    <!-- AI Tools — hover to open fixed submenu -->
    <button
      ref="aiTriggerRef"
      @mouseenter="openAiSubmenu"
      class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2"
    >
      <Sparkles :size="12" /> AI Tools
      <ChevronRight :size="10" class="ml-auto" />
    </button>
  </div>

  <!-- AI Tools submenu — fixed positioned to avoid clipping -->
  <div
    v-if="showAiSubmenu && visible && !aiResult && !aiLoading"
    class="fixed z-[210] bg-surface border border-border rounded shadow-2xl py-1 w-52"
    :style="{ left: submenuPos.x + 'px', top: submenuPos.y + 'px' }"
    @click.stop
    @mouseenter="showAiSubmenu = true"
    @mouseleave="closeSubmenu"
  >
    <button
      v-for="tool in AI_TOOLS"
      :key="tool.id"
      @click="emit('runAiTool', tool.id); emit('close'); closeSubmenu()"
      class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2"
    >
      <component :is="tool.icon" :size="12" /> {{ tool.label }}
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
        <Sparkles :size="10" /> {{ activeTool?.label ?? aiResultMode }} {{ aiLoading ? 'Running...' : 'Result' }}
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

      <!-- Parameter selector for the active tool (tone / voice / language) -->
      <div v-if="activeTool?.param" class="px-3 pb-1 flex flex-wrap gap-1">
        <button
          v-for="opt in paramOptions"
          :key="opt"
          @click="emit('applyToolParam', opt)"
          class="px-1.5 py-0.5 rounded text-[9px] font-medium cursor-pointer transition-colors capitalize"
          :class="aiParamValue === opt ? 'bg-accent/20 text-accent border border-accent/30' : 'bg-surface-hover text-text-secondary hover:text-text-primary border border-transparent'"
        >{{ opt }}</button>
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
