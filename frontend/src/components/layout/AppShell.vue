<script setup lang="ts">
import { useUiStore } from '../../stores/ui'
import Sidebar from './Sidebar.vue'
import PanelSplitter from './PanelSplitter.vue'
import EntryDetail from '../entry/EntryDetail.vue'
import EntryEditor from '../entry/EntryEditor.vue'
import AiDrawerPanel from '../entry/AiDrawerPanel.vue'
import SearchPalette from '../search/SearchPalette.vue'
import { useEntriesStore } from '../../stores/entries'
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { AlertTriangle, Save, Trash2, X, Sparkles } from 'lucide-vue-next'

const ui = useUiStore()
const entries = useEntriesStore()
const editorRef = ref<InstanceType<typeof EntryEditor> | null>(null)

const showDetail = computed(() => ui.detailPanelOpen && entries.currentEntry && !ui.showEditor)
const showEditor = computed(() => ui.showEditor)
const showAiDrawer = computed(() => ui.aiDrawerOpen && showEditor.value)

// ── Global Ctrl+K for search palette ──
function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    ui.openSearchPalette()
  }
}
onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))

// ── Save prompt actions ──
async function handleSave() {
  await editorRef.value?.save()
  const pending = ui.pendingSwitch
  ui.confirmSwitchSave()
  if (pending) ui.startEditing(pending.entryId, pending.date)
}

function handleDiscard() {
  ui.confirmSwitchDiscard()
}

function handleCancel() {
  ui.cancelSwitch()
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface">
    <!-- Sidebar -->
    <Sidebar />

    <!-- Center panel -->
    <main class="flex-1 flex flex-col min-w-0 bg-surface relative">
      <router-view />

      <!-- Save prompt overlay -->
      <Transition name="prompt">
        <div
          v-if="ui.showSavePrompt"
          class="absolute inset-0 bg-black/30 flex items-center justify-center z-50"
        >
          <div class="bg-surface border border-border rounded-lg p-4 w-72 shadow-xl space-y-3">
            <div class="flex items-center gap-2 text-sm font-medium text-text-primary">
              <AlertTriangle :size="16" class="text-amber-400" />
              Unsaved changes
            </div>
            <p class="text-xs text-text-secondary">You have unsaved content. Save before switching?</p>
            <div class="flex gap-2 justify-end">
              <button
                class="flex items-center gap-1 px-2.5 py-1 text-xs bg-danger/15 text-danger hover:bg-danger/25 rounded cursor-pointer transition-colors"
                @click="handleDiscard"
              >
                <Trash2 :size="12" /> Discard
              </button>
              <button
                class="flex items-center gap-1 px-2.5 py-1 text-xs bg-surface-hover text-text-secondary hover:text-text-primary rounded cursor-pointer transition-colors"
                @click="handleCancel"
              >
                <X :size="12" /> Cancel
              </button>
              <button
                class="flex items-center gap-1 px-2.5 py-1 text-xs bg-accent text-white hover:bg-accent/90 rounded cursor-pointer transition-colors"
                @click="handleSave"
              >
                <Save :size="12" /> Save
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </main>

    <!-- AI Drawer (side panel between calendar and editor) -->
    <Transition name="ai-drawer">
      <div
        v-if="showAiDrawer"
        class="shrink-0 w-80 bg-surface border-l border-r border-border overflow-y-auto flex flex-col"
      >
        <div class="flex items-center justify-between px-3 py-2 border-b border-border">
          <span class="text-xs font-medium text-text-primary flex items-center gap-1"><Sparkles :size="14" /> AI Assistant</span>
          <button @click="ui.aiDrawerOpen = false" class="text-text-muted hover:text-text-primary cursor-pointer"><X :size="14" /></button>
        </div>
        <AiDrawerPanel
          :get-selection="() => editorRef?.body ?? ''"
          :apply-text="(t: string) => { if (editorRef) { editorRef.body = t; editorRef.onInput() } }"
          :has-entry="!!editorRef?.hasEntry"
          :entry-id="editorRef?.entryId ?? null"
        />
      </div>
    </Transition>

    <!-- Panel splitter -->
    <PanelSplitter v-if="showDetail || showEditor" />

    <!-- Right panel: entry detail or editor -->
    <div
      v-if="showDetail || showEditor"
      class="shrink-0 bg-editor border-l border-border overflow-y-auto"
      :style="{ width: ui.rightPanelWidth + 'px' }"
    >
      <EntryEditor v-if="showEditor" ref="editorRef" />
      <EntryDetail v-else />
    </div>

    <!-- Global search palette -->
    <SearchPalette v-if="ui.searchPaletteOpen" />
  </div>
</template>

<style scoped>
.prompt-enter-active,
.prompt-leave-active {
  transition: all 0.2s ease;
}
.prompt-enter-from,
.prompt-leave-to {
  opacity: 0;
}
.ai-drawer-enter-active,
.ai-drawer-leave-active {
  transition: all 0.2s ease;
}
.ai-drawer-enter-from,
.ai-drawer-leave-to {
  opacity: 0;
  width: 0;
}
</style>
