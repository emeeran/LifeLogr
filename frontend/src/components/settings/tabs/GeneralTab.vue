<script setup lang="ts">
import { onMounted } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useUiStore } from '../../../stores/ui'
import { useSearchStore } from '../../../stores/search'
import { useTemplatesStore } from '../../../stores/templates'
import {
  Sun, Moon, Type, Sliders, Clock, Eye, Search, MapPin, LayoutTemplate, Keyboard
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'
import AccordionItem from '../shared/AccordionItem.vue'

const ui = useUiStore()
const searchStore = useSearchStore()
const templatesStore = useTemplatesStore()

// Fetch templates so the "Default template" dropdown is populated
onMounted(() => { templatesStore.fetchAll() })

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
  <SettingsSection title="Appearance" :icon="Sun" description="Customize the look and feel"
    reset-label="Reset" @reset="resetAppearanceDefaults">
    <SettingRow label="Dark mode">
      <template #icon>
        <component :is="ui.darkMode ? Moon : Sun" :size="12" class="text-text-muted shrink-0" />
      </template>
      <ToggleSwitch :model-value="ui.darkMode" @update:model-value="ui.toggleTheme()" />
    </SettingRow>
    <SettingRow :icon="Type" label="Font family">
      <select :value="ui.fontFamily" @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)"
        class="settings-select max-w-40">
        <option v-for="f in fontOptions" :key="f.value" :value="f.value">{{ f.label }}</option>
      </select>
    </SettingRow>
    <SettingRow :icon="Type" :label="`Font size (${ui.fontSize}px)`">
      <input type="range" :value="ui.fontSize" @input="ui.setFontSize(+($event.target as HTMLInputElement).value)"
        min="12" max="20" step="1" class="w-24 accent-accent" />
    </SettingRow>
  </SettingsSection>

  <!-- Editor & Writing -->
  <SettingsSection title="Editor & Writing" :icon="Sliders" description="Writing behavior, search, and preferences"
    reset-label="Reset" @reset="resetEditorDefaults" card-class="p-3 space-y-2">
    <SettingRow :icon="Clock" :label="`Auto-save (${autosaveInterval}s)`">
      <input type="range" v-model.number="autosaveInterval" min="1" max="10" step="1" class="w-24 accent-accent" />
    </SettingRow>
    <SettingRow :icon="Eye" label="OCR language">
      <select v-model="ocrLanguage" class="settings-select w-32">
        <option v-for="l in ocrLanguages" :key="l.value" :value="l.value">{{ l.label }}</option>
      </select>
    </SettingRow>
    <SettingRow :icon="Type" label="Default title">
      <input v-model="ui.defaultTitle" placeholder="e.g. Daily Journal" class="settings-input w-40" />
    </SettingRow>

    <div class="border-t border-border pt-2 space-y-2">
      <SettingRow :icon="Search" label="Search mode">
        <select v-model="searchStore.searchMode" class="settings-select w-32">
          <option value="hybrid">Hybrid</option>
          <option value="keyword">Keyword</option>
          <option value="semantic">Semantic</option>
        </select>
      </SettingRow>
      <p class="text-[10px] text-text-muted pl-[30px]">
        <span v-if="searchStore.searchMode === 'hybrid'">Combines keyword and semantic search for best results.</span>
        <span v-else-if="searchStore.searchMode === 'keyword'">Fast text matching. Works without AI models.</span>
        <span v-else>Finds entries by meaning, not just words. Requires embedding model.</span>
      </p>
    </div>

    <div class="border-t border-border pt-2 space-y-2">
      <SettingRow label="Auto-tag location">
        <template #icon>
          <MapPin :size="12" class="text-text-muted shrink-0" />
        </template>
        <ToggleSwitch v-model="autoGeotag" />
      </SettingRow>
      <SettingRow :icon="LayoutTemplate" label="Default template">
        <select v-model.number="defaultTemplateId" class="settings-select max-w-40">
          <option :value="null">None</option>
          <option v-for="t in templatesStore.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </SettingRow>
    </div>
  </SettingsSection>

  <!-- Keyboard Shortcuts (collapsible) -->
  <AccordionItem title="Keyboard Shortcuts" :icon="Keyboard" description="Quick reference for editor shortcuts">
    <div class="divide-y divide-border -m-3">
      <div v-for="s in shortcuts" :key="s.keys" class="flex items-center justify-between px-3 py-1.5">
        <span class="text-[12px] text-text-secondary">{{ s.desc }}</span>
        <kbd class="px-1.5 py-0.5 bg-surface-hover rounded-md text-[10px] font-mono text-text-muted border border-border">{{ s.keys }}</kbd>
      </div>
    </div>
  </AccordionItem>
</template>
