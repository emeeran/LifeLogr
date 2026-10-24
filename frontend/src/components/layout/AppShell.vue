<script setup lang="ts">
import { useUiStore } from '../../stores/ui'
import { mediaApi } from '../../api/media'
import Sidebar from './Sidebar.vue'
import PanelSplitter from './PanelSplitter.vue'
import EntryDetail from '../entry/EntryDetail.vue'
import EntryEditor from '../entry/EntryEditor.vue'
const AiDrawerPanel = defineAsyncComponent(
  () => import('../entry/AiDrawerPanel.vue'),
)
const AttachmentsPanel = defineAsyncComponent(
  () => import('../entry/AttachmentsPanel.vue'),
)
import SearchPalette from '../search/SearchPalette.vue'
import { useToastStore } from '../../stores/toast'
import ScribblePad from '../scribble/ScribblePad.vue'
const WhatsNewDialog = defineAsyncComponent(
  () => import('../settings/dialogs/WhatsNewDialog.vue'),
)
const KeyboardShortcutsDialog = defineAsyncComponent(
  () => import('../common/KeyboardShortcutsDialog.vue'),
)
const NowPlayingBar = defineAsyncComponent(
  () => import('../common/NowPlayingBar.vue'),
)
import { useEntriesStore } from '../../stores/entries'
import { useUpdateChecker } from '../../composables/useUpdateChecker'
import {
  computed,
  ref,
  onMounted,
  defineAsyncComponent,
} from 'vue'
import {
  AlertTriangle,
  Save,
  Trash2,
  X,
  Sparkles,
  Paperclip,
} from 'lucide-vue-next'
import { useLocalStorage } from '@vueuse/core'
import type { Component } from 'vue'
import { errorMessage } from '../../utils/errorMessage'
import { useModalFocus } from '../../composables/useModalFocus'
import { useHotkey } from '../../composables/useHotkey'

const ui = useUiStore()
const entries = useEntriesStore()
const toast = useToastStore()
const editorRef = ref<InstanceType<typeof EntryEditor> | null>(null)
// OCR language from Settings → Appearance (same key the settings tab writes).
const ocrLang = useLocalStorage<string>('lifelogr-ocr-language', 'eng')

const showDetail = computed(
  () => ui.detailPanelOpen && entries.currentEntry && !ui.showEditor,
)
const showEditor = computed(() => ui.showEditor)
const showDrawer = computed(() => ui.activeDrawer !== null && showEditor.value)

// The shared journal editor + detail surface belongs only to the Journal
// (calendar) view. Notes has its own editor inside NotesView; every other view
// is full-bleed, so the right panel + splitter stay hidden off-calendar.
const isJournalView = computed(() => ui.activeView === 'calendar')

const drawerTitle = computed(() => {
  switch (ui.activeDrawer) {
    case 'ai':
      return 'AI Assistant'
    case 'attachments':
      return 'Attachments'
    default:
      return ''
  }
})

const drawerIcon = computed<Component>(() => {
  switch (ui.activeDrawer) {
    case 'ai':
      return Sparkles
    case 'attachments':
      return Paperclip
    default:
      return Sparkles
  }
})

// ── Global shortcuts (useHotkey: one shared keydown listener, auto-cleaned) ──
// The typing guard keeps these out of the editors' textareas, so Ctrl+K stays
// inline code while typing and opens search everywhere else.
const showShortcuts = ref(false)
function openShortcuts() {
  showShortcuts.value = true
}
useHotkey('mod+k', () => ui.openSearchPalette())
useHotkey('mod+.', () => ui.toggleZenMode())
useHotkey('mod+,', () => ui.setView('settings'))
useHotkey('mod+/', openShortcuts)
useHotkey('?', openShortcuts)

// ── First-run "What's New" dialog + weekly auto update check ──
const { hasUnseenVersion, maybeAutoCheck } = useUpdateChecker()
const showWhatsNew = ref(false)
onMounted(() => {
  // Show the changelog dialog once per version upgrade (or on fresh install).
  if (hasUnseenVersion) {
    // Defer a tick so the app shell renders first.
    setTimeout(() => {
      showWhatsNew.value = true
    }, 300)
  }
  // Best-effort weekly background check (opt-in via General settings).
  // Fire-and-forget — must never interrupt startup or the user.
  void maybeAutoCheck()
})

// ── Save prompt actions ──
async function handleSave() {
  // save() resolves false when nothing was written — switching anyway would
  // abandon the edits the user just asked to save.
  const saved = (await editorRef.value?.save()) !== false
  if (!saved) {
    toast.error('Save failed — staying on this entry.')
    ui.cancelSwitch()
    return
  }
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

// Save-prompt dialog a11y: focus trap + Esc + focus restore.
const savePromptModal = useModalFocus(
  () => ui.showSavePrompt,
  () => handleCancel(),
)

// ── Drawer panel callbacks ──
function onAttachmentView(index: number) {
  editorRef.value?.openViewer?.(index)
}

async function onExtractText(id: number) {
  try {
    const { text } = await mediaApi.extractText(id, ocrLang.value)
    // Append through the editor's own input chain (dirty flag, autosave,
    // preview re-render) instead of mutating its internals from outside.
    const appended = editorRef.value?.appendTextWithOcr(text)
    if (!appended) toast.info('No text was detected in this image.')
  } catch (e: unknown) {
    toast.error(`OCR failed: ${errorMessage(e)}`)
  }
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface">
    <!-- Sidebar -->
    <Sidebar v-show="!ui.zenMode" />

    <!-- Scribble Pad (slide-in panel) -->
    <Transition name="scribble-slide">
      <div
        v-if="ui.scribbleOpen && !ui.zenMode"
        class="shrink-0 w-[280px] overflow-hidden"
      >
        <ScribblePad @close="ui.scribbleOpen = false" />
      </div>
    </Transition>

    <!-- Center panel (kept mounted even when drawer is open; just narrows) -->
    <main
      v-show="!showDrawer && !ui.zenMode"
      class="flex-1 flex flex-col min-w-0 bg-surface relative"
    >
      <router-view v-slot="{ Component }">
        <Transition name="route-fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </router-view>

      <!-- Save prompt overlay -->
      <Transition name="prompt">
        <div
          v-if="ui.showSavePrompt"
          class="absolute inset-0 bg-black/30 flex items-center justify-center z-50"
        >
          <div
            ref="savePromptModal.container"
            role="dialog"
            aria-modal="true"
            aria-label="Unsaved changes"
            tabindex="-1"
            class="glass-panel rounded-lg p-4 w-72 space-y-3"
            @keydown="savePromptModal.onKeydown"
          >
            <div
              class="flex items-center gap-2 text-sm font-medium text-text-primary"
            >
              <AlertTriangle :size="16" class="text-amber-400" />
              Unsaved changes
            </div>
            <p class="text-xs text-text-secondary">
              You have unsaved content. Save before switching?
            </p>
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

    <!-- Tool Drawer (side panel between calendar and editor) -->
    <Transition name="ai-drawer">
      <div
        v-if="showDrawer"
        class="shrink-0 w-80 bg-surface border-l border-r border-border overflow-y-auto overflow-x-hidden flex flex-col relative z-10"
      >
        <div
          class="flex items-center justify-between px-3 py-2 border-b border-border"
        >
          <span
            class="text-xs font-medium text-text-primary flex items-center gap-1"
          >
            <component :is="drawerIcon" :size="14" /> {{ drawerTitle }}
          </span>
          <button
            @click="ui.closeDrawer()"
            class="text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X :size="14" />
          </button>
        </div>
        <!-- Dynamic panel content -->
        <AiDrawerPanel
          v-if="ui.activeDrawer === 'ai'"
          :get-selection="() => editorRef?.getSelection?.() ?? ''"
          :apply-text="
            (t: string) => {
              editorRef?.applyToSelection?.(t)
            }
          "
          :has-entry="!!editorRef?.hasEntry"
          :entry-id="editorRef?.entryId ?? null"
        />
        <AttachmentsPanel
          v-if="ui.activeDrawer === 'attachments'"
          :attachments="editorRef?.attachments ?? []"
          @add="editorRef?.triggerFileInput?.()"
          @remove="(id: number) => editorRef?.removeAttachment?.(id)"
          @view="onAttachmentView"
          @extract-text="onExtractText"
        />
      </div>
    </Transition>

    <!-- Panel splitter -->
    <PanelSplitter
      v-if="!ui.zenMode && isJournalView && (showDetail || showEditor)"
      :model-value="ui.rightPanelWidth"
      :min="280"
      :max="1200"
      side="right"
      @update:model-value="ui.setRightPanelWidth"
    />

    <!-- Right panel: entry detail or editor (full-width when Zen Mode is on) -->
    <div
      v-if="
        isJournalView && (ui.zenMode ? showEditor : showDetail || showEditor)
      "
      class="bg-editor overflow-y-auto transition-all duration-200"
      :class="ui.zenMode ? 'flex-1 min-w-0' : 'shrink-0 border-l border-border'"
      :style="ui.zenMode ? undefined : { width: ui.rightPanelWidth + 'px' }"
    >
      <EntryEditor v-if="showEditor" ref="editorRef" />
      <EntryDetail v-else />
    </div>

    <!-- Global search palette -->
    <SearchPalette v-if="ui.searchPaletteOpen" />

    <!-- First-run / upgrade "What's New" dialog -->
    <WhatsNewDialog v-model="showWhatsNew" />

    <!-- Keyboard shortcuts cheatsheet (? / Ctrl+/) -->
    <KeyboardShortcutsDialog
      v-if="showShortcuts"
      @close="showShortcuts = false"
    />

    <!-- Read-aloud now-playing bar (shared tts store) -->
    <NowPlayingBar />

    <!-- Zen mode exit affordance -->
    <button
      v-if="ui.zenMode"
      class="fixed top-3 right-3 z-50 flex items-center gap-1 px-2.5 py-1.5 rounded-full glass-panel text-xs text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
      title="Exit Zen Mode (Ctrl+.)"
      @click="ui.toggleZenMode()"
    >
      <X :size="12" /> Exit Zen
    </button>
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
.scribble-slide-enter-active,
.scribble-slide-leave-active {
  transition: all 0.2s ease;
}
.scribble-slide-enter-from,
.scribble-slide-leave-to {
  opacity: 0;
  width: 0;
}

/* Route transition — smooth fade between views */
.route-fade-enter-active,
.route-fade-leave-active {
  transition: opacity 0.15s ease;
}
.route-fade-enter-from,
.route-fade-leave-to {
  opacity: 0;
}
</style>
