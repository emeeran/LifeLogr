<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { useUiStore } from '../../../stores/ui'
import { useSearchStore } from '../../../stores/search'
import { useTemplatesStore } from '../../../stores/templates'
import {
  Sun, Moon, Type, Sliders, Clock, Eye, Search, MapPin, LayoutTemplate, Keyboard
} from 'lucide-vue-next'

const ui = useUiStore()
const searchStore = useSearchStore()
const templatesStore = useTemplatesStore()

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

// ── Preferences ──
const autoGeotag = useLocalStorage<boolean>('diarium-auto-geotag', false)
const defaultTemplateId = useLocalStorage<number | null>('diarium-default-template', null)

// ── Appearance ──
const fontOptions = [
  { value: 'system-ui', label: 'System UI' },
  { value: 'Georgia, serif', label: 'Georgia (Serif)' },
  { value: "'Merriweather', serif", label: 'Merriweather' },
  { value: "'Noto Serif', serif", label: 'Noto Serif' },
  { value: "monospace", label: 'Monospace' },
]

// ── Editor ──
const autosaveInterval = useLocalStorage<number>('diarium-autosave-interval', 2)
const ocrLanguage = useLocalStorage<string>('diarium-ocr-language', 'eng')
const ocrLanguages = [
  { value: 'eng', label: 'English' },
  { value: 'fra', label: 'French' },
  { value: 'deu', label: 'German' },
  { value: 'spa', label: 'Spanish' },
  { value: 'por', label: 'Portuguese' },
  { value: 'ita', label: 'Italian' },
  { value: 'nld', label: 'Dutch' },
  { value: 'pol', label: 'Polish' },
  { value: 'rus', label: 'Russian' },
  { value: 'jpn', label: 'Japanese' },
  { value: 'chi_sim', label: 'Chinese (Simplified)' },
  { value: 'ara', label: 'Arabic' },
  { value: 'hin', label: 'Hindi' },
]

const shortcuts = [
  { keys: 'Ctrl + K', desc: 'Open search palette' },
  { keys: 'Ctrl + S', desc: 'Save entry' },
  { keys: 'Ctrl + B', desc: 'Bold text' },
  { keys: 'Ctrl + I', desc: 'Italic text' },
  { keys: 'Ctrl + Shift + X', desc: 'Strikethrough' },
  { keys: 'Ctrl + \\', desc: 'Remove formatting' },
  { keys: 'Ctrl + Z', desc: 'Undo' },
  { keys: 'Ctrl + Shift + Z', desc: 'Redo' },
  { keys: 'Ctrl + F', desc: 'Find in entry' },
  { keys: 'Escape', desc: 'Close panel / dialog' },
]

function resetAppearanceDefaults() {
  ui.setFontFamily('system-ui')
  ui.setFontSize(14)
  if (!ui.darkMode) ui.toggleTheme()
  emit('toast', 'success', 'Appearance reset to defaults')
}

function resetEditorDefaults() {
  autosaveInterval.value = 2
  ocrLanguage.value = 'eng'
  ui.defaultTitle = ''
  emit('toast', 'success', 'Editor settings reset to defaults')
}
</script>

<template>
  <!-- Appearance -->
  <section>
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1">
        <Sun :size="11" /> Appearance
      </h3>
      <button @click="resetAppearanceDefaults"
        class="text-[9px] text-text-muted hover:text-accent cursor-pointer transition-colors">Reset defaults</button>
    </div>
    <div class="bg-surface rounded p-2 border border-border space-y-1.5">
      <label class="flex items-center gap-2 cursor-pointer">
        <component :is="ui.darkMode ? Moon : Sun" :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Dark mode</span>
        <input type="checkbox" :checked="ui.darkMode" @change="ui.toggleTheme()" class="accent-accent" />
      </label>
      <div class="flex items-center gap-2">
        <Type :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Font family</span>
        <select
          :value="ui.fontFamily"
          @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]"
        >
          <option v-for="f in fontOptions" :key="f.value" :value="f.value">{{ f.label }}</option>
        </select>
      </div>
      <div class="flex items-center gap-2">
        <Type :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Font size ({{ ui.fontSize }}px)</span>
        <input type="range" :value="ui.fontSize" @input="ui.setFontSize(+($event.target as HTMLInputElement).value)"
          min="12" max="20" step="1" class="w-20 accent-accent" />
      </div>
    </div>
  </section>

  <!-- Editor -->
  <section>
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1">
        <Sliders :size="11" /> Editor
      </h3>
      <button @click="resetEditorDefaults"
        class="text-[9px] text-text-muted hover:text-accent cursor-pointer transition-colors">Reset defaults</button>
    </div>
    <div class="bg-surface rounded p-2 border border-border space-y-1.5">
      <div class="flex items-center gap-2">
        <Clock :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Auto-save ({{ autosaveInterval }}s)</span>
        <input type="range" v-model.number="autosaveInterval" min="1" max="10" step="1" class="w-20 accent-accent" />
      </div>
      <div class="flex items-center gap-2">
        <Eye :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">OCR language</span>
        <select v-model="ocrLanguage"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[140px]">
          <option v-for="l in ocrLanguages" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </div>
      <div class="flex items-center gap-2">
        <Type :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Default title</span>
        <input v-model="ui.defaultTitle"
          placeholder="e.g. Daily Journal"
          class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none w-32 hover:border-accent transition-colors" />
      </div>
    </div>
  </section>

  <!-- Search -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Search :size="11" /> Search
    </h3>
    <div class="bg-surface rounded p-2 border border-border">
      <div class="flex items-center gap-2">
        <Search :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Search mode</span>
        <select v-model="searchStore.searchMode"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[120px]">
          <option value="hybrid">Hybrid</option>
          <option value="keyword">Keyword</option>
          <option value="semantic">Semantic</option>
        </select>
      </div>
      <div class="text-[9px] text-text-muted mt-1">
        <span v-if="searchStore.searchMode === 'hybrid'">Combines keyword and semantic search for best results.</span>
        <span v-else-if="searchStore.searchMode === 'keyword'">Fast text matching. Works without AI models.</span>
        <span v-else>Finds entries by meaning, not just words. Requires embedding model.</span>
      </div>
    </div>
  </section>

  <!-- Preferences -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide mb-1">Preferences</h3>
    <div class="bg-surface rounded p-2 border border-border space-y-1.5">
      <label class="flex items-center gap-2 cursor-pointer">
        <MapPin :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Auto-tag location</span>
        <input type="checkbox" v-model="autoGeotag" class="accent-accent" />
      </label>
      <div class="flex items-center gap-2">
        <LayoutTemplate :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Default template</span>
        <select v-model.number="defaultTemplateId"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]">
          <option :value="null">None</option>
          <option v-for="t in templatesStore.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </div>
    </div>
  </section>

  <!-- Keyboard Shortcuts -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Keyboard :size="11" /> Keyboard Shortcuts
    </h3>
    <div class="bg-surface rounded border border-border overflow-hidden">
      <div class="divide-y divide-border">
        <div v-for="s in shortcuts" :key="s.keys" class="flex items-center justify-between px-2 py-1">
          <span class="text-[11px] text-text-secondary">{{ s.desc }}</span>
          <kbd class="px-1.5 py-0.5 bg-surface-hover rounded text-[9px] font-mono text-text-muted border border-border">{{ s.keys }}</kbd>
        </div>
      </div>
    </div>
  </section>
</template>
