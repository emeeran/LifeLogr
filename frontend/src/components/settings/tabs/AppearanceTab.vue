<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useUiStore } from '../../../stores/ui'
import { useSearchStore } from '../../../stores/search'
import { useTemplatesStore } from '../../../stores/templates'
import { API_ORIGIN } from '../../../api/client'
import { ttsApi } from '../../../api/tts'
import {
  Sun, Moon, Type, Sliders, Clock, Eye, ScanText, Search, LayoutTemplate, Keyboard,
  Volume2, Play, X,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'
import AccordionItem from '../shared/AccordionItem.vue'
import SettingGroup from '../shared/SettingGroup.vue'
import SButton from '../shared/SButton.vue'

interface TTSVoice { short_name: string; locale: string; gender: string }

function voiceLabel(v: TTSVoice): string {
  const name = v.short_name.replace(/Neural$/, '').replace(/V2$/, '')
  const parts = name.split('-')
  const voiceName = parts.length > 2 ? parts.slice(2).join(' ') : parts[parts.length - 1]
  const gender = v.gender === 'Female' ? 'F' : v.gender === 'Male' ? 'M' : ''
  return `${voiceName} ${gender ? `(${gender})` : ''}`.trim()
}

const LOCALE_LABELS: Record<string, string> = {
  'en-US': 'English (US)', 'en-GB': 'English (UK)', 'en-AU': 'English (AU)',
  'en-CA': 'English (CA)', 'en-IN': 'English (IN)', 'en-IE': 'English (IE)',
  'fr-FR': 'French', 'fr-CA': 'French (CA)', 'de-DE': 'German', 'de-AT': 'German (AT)',
  'es-ES': 'Spanish', 'es-MX': 'Spanish (MX)', 'pt-BR': 'Portuguese (BR)',
  'pt-PT': 'Portuguese (PT)', 'it-IT': 'Italian', 'nl-NL': 'Dutch', 'pl-PL': 'Polish',
  'ru-RU': 'Russian', 'ja-JP': 'Japanese', 'zh-CN': 'Chinese (CN)', 'zh-TW': 'Chinese (TW)',
  'ko-KR': 'Korean', 'ar-SA': 'Arabic', 'hi-IN': 'Hindi', 'sv-SE': 'Swedish',
  'da-DK': 'Danish', 'fi-FI': 'Finnish', 'nb-NO': 'Norwegian', 'tr-TR': 'Turkish',
}
function localeLabel(locale: string): string { return LOCALE_LABELS[locale] ?? locale }
function voicesByLocale(voices: TTSVoice[]): Map<string, TTSVoice[]> {
  const groups = new Map<string, TTSVoice[]>()
  for (const v of voices) { const list = groups.get(v.locale) ?? []; list.push(v); groups.set(v.locale, list) }
  return groups
}

const ui = useUiStore()
const searchStore = useSearchStore()
const templatesStore = useTemplatesStore()

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()
function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

// ── Preferences ──
const defaultTemplateId = useLocalStorage<number | null>('lifelogr-default-template', null)

// ── Appearance ──
const fontOptions = [
  { value: 'system-ui', label: 'System UI' },
  { value: 'Georgia, serif', label: 'Georgia (Serif)' },
  { value: "'Merriweather', serif", label: 'Merriweather' },
  { value: "'Noto Serif', serif", label: 'Noto Serif' },
  { value: 'monospace', label: 'Monospace' },
]

// ── Editor ──
const autosaveInterval = useLocalStorage<number>('lifelogr-autosave-interval', 2)
const ocrLanguage = useLocalStorage<string>('lifelogr-ocr-language', 'eng')
const ocrLanguages = [
  { value: 'eng', label: 'English' },
  { value: 'tam', label: 'Tamil' },
]
// Whether image attachments are OCR'd automatically on add (entry inline-embed +
// note paste/drop/snip). Off = keep images as-is; manual "Extract text" still works.
const autoOcrImages = useLocalStorage<boolean>('lifelogr-auto-ocr-images', true)

// ── Read aloud (TTS) ──
const ttsSpeed = useLocalStorage<number>('lifelogr-tts-speed', 1.0)
const ttsVolume = useLocalStorage<number>('lifelogr-tts-volume', 100)
const ttsVoice = useLocalStorage<string>('lifelogr-tts-voice', 'en-US-AvaNeural')
const ttsPitch = useLocalStorage<number>('lifelogr-tts-pitch', 0)
const ttsVoices = ref<TTSVoice[]>([])
const ttsVoicesLoading = ref(false)
const ttsPreviewing = ref(false)
let previewAudio: HTMLAudioElement | null = null

async function loadVoices() {
  ttsVoicesLoading.value = true
  try {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/voices`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    ttsVoices.value = await res.json()
  } catch { /* ignore */ } finally { ttsVoicesLoading.value = false }
}

/** Speak a short sample using the currently-selected voice/speed/volume. */
async function previewVoice() {
  if (ttsPreviewing.value && previewAudio) { previewAudio.pause(); ttsPreviewing.value = false; return }
  ttsPreviewing.value = true
  try {
    const { key } = await ttsApi.speakUrl('This is how your journal will sound when read aloud.')
    if (!key) { ttsPreviewing.value = false; return }
    previewAudio = new Audio(ttsApi.fileUrl(key))
    previewAudio.volume = ttsVolume.value / 100
    previewAudio.onended = () => { ttsPreviewing.value = false }
    await previewAudio.play()
  } catch (e: unknown) {
    ttsPreviewing.value = false
    emit('toast', 'error', `Voice preview failed: ${errMsg(e)}`)
  }
}

function resetTTSDefaults() {
  ttsVoice.value = 'en-US-AvaNeural'; ttsSpeed.value = 1.0; ttsVolume.value = 100; ttsPitch.value = 0
  emit('toast', 'success', 'Read-aloud settings reset to defaults')
}

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
  ui.setFontFamily('system-ui'); ui.setFontSize(14)
  if (!ui.darkMode) ui.toggleTheme()
  emit('toast', 'success', 'Appearance reset to defaults')
}

function resetEditorDefaults() {
  autosaveInterval.value = 2; ocrLanguage.value = 'eng'; ui.defaultTitle = ''
  emit('toast', 'success', 'Editor settings reset to defaults')
}

onMounted(() => { templatesStore.fetchAll(); loadVoices() })
</script>

<template>
  <SettingsSection title="Appearance" :icon="Sun" description="Customize the look and feel" setting-key="Appearance"
    reset-label="Reset" @reset="resetAppearanceDefaults">
    <SettingRow label="Dark mode">
      <template #icon>
        <component :is="ui.darkMode ? Moon : Sun" :size="13" class="text-text-muted shrink-0" aria-hidden="true" />
      </template>
      <ToggleSwitch :model-value="ui.darkMode" @update:model-value="ui.toggleTheme()" />
    </SettingRow>
    <SettingRow :icon="Type" label="Font family">
      <select :value="ui.fontFamily" @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)" class="settings-select max-w-44">
        <option v-for="f in fontOptions" :key="f.value" :value="f.value">{{ f.label }}</option>
      </select>
    </SettingRow>
    <SettingRow :icon="Type" :label="`Font size (${ui.fontSize}px)`">
      <input type="range" :value="ui.fontSize" @input="ui.setFontSize(+($event.target as HTMLInputElement).value)"
        min="12" max="20" step="1" class="w-28 accent-accent" />
    </SettingRow>
  </SettingsSection>

  <SettingsSection title="Editor & Writing" :icon="Sliders" description="Writing behavior, search, and preferences"
    reset-label="Reset" @reset="resetEditorDefaults" card-class="p-3">
    <SettingGroup label="Writing">
      <SettingRow :icon="Clock" :label="`Auto-save (${autosaveInterval}s)`"
        description="How often unsaved entry changes are written to disk.">
        <input type="range" v-model.number="autosaveInterval" min="1" max="10" step="1" class="w-28 accent-accent" />
      </SettingRow>
      <SettingRow :icon="Eye" label="OCR language" description="Used when extracting text from attached images.">
        <select v-model="ocrLanguage" class="settings-select w-36">
          <option v-for="l in ocrLanguages" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </SettingRow>
      <SettingRow :icon="ScanText" label="Auto-OCR images"
        description="Extract text from images automatically when you add them. Off keeps images as-is — you can still OCR any image manually.">
        <ToggleSwitch v-model="autoOcrImages" />
      </SettingRow>
      <SettingRow :icon="Type" label="Default title">
        <input v-model="ui.defaultTitle" placeholder="e.g. Daily Journal" class="settings-input w-44" />
      </SettingRow>
    </SettingGroup>

    <SettingGroup label="Search">
      <SettingRow :icon="Search" label="Search mode">
        <select v-model="searchStore.searchMode" class="settings-select w-32">
          <option value="hybrid">Hybrid</option>
          <option value="keyword">Keyword</option>
          <option value="semantic">Semantic</option>
        </select>
      </SettingRow>
      <p class="text-[10.5px] text-text-muted pl-[31px] leading-snug">
        <span v-if="searchStore.searchMode === 'hybrid'">Combines keyword and semantic search for best results.</span>
        <span v-else-if="searchStore.searchMode === 'keyword'">Fast text matching. Works without AI models.</span>
        <span v-else>Finds entries by meaning, not just words. Requires an embedding model.</span>
      </p>
    </SettingGroup>

    <SettingGroup label="Preferences">
      <SettingRow :icon="LayoutTemplate" label="Default template">
        <select v-model.number="defaultTemplateId" class="settings-select max-w-44">
          <option :value="null">None</option>
          <option v-for="t in templatesStore.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </SettingRow>
    </SettingGroup>
  </SettingsSection>

  <SettingsSection title="Read Aloud" :icon="Volume2" description="Text-to-speech voice settings" setting-key="Voice"
    reset-label="Reset" @reset="resetTTSDefaults">
    <SettingRow :icon="Volume2" label="Voice" description="Voice used when reading entries aloud.">
      <select v-model="ttsVoice" class="settings-select max-w-44" :disabled="ttsVoicesLoading">
        <option v-if="ttsVoicesLoading" disabled value="">Loading voices...</option>
        <template v-for="[locale, voices] in voicesByLocale(ttsVoices)" :key="locale">
          <optgroup :label="localeLabel(locale)">
            <option v-for="v in voices" :key="v.short_name" :value="v.short_name">{{ voiceLabel(v) }}</option>
          </optgroup>
        </template>
      </select>
    </SettingRow>
    <SettingRow indent :label="`Speed (${ttsSpeed.toFixed(1)}x)`">
      <input type="range" v-model.number="ttsSpeed" min="0.5" max="2.0" step="0.1" class="w-28 accent-accent" />
    </SettingRow>
    <SettingRow indent :label="`Volume (${ttsVolume}%)`">
      <input type="range" v-model.number="ttsVolume" min="0" max="100" step="5" class="w-28 accent-accent" />
    </SettingRow>
    <SettingRow indent :label="`Pitch (${ttsPitch > 0 ? '+' : ''}${ttsPitch} Hz)`"
      description="Lower for a deeper, warmer voice; raise for brighter. Applies to journals and notes.">
      <input type="range" v-model.number="ttsPitch" min="-40" max="40" step="5" class="w-28 accent-accent" />
    </SettingRow>
    <div class="pl-[31px]">
      <SButton variant="outline" size="xs" :icon="ttsPreviewing ? X : Play" :disabled="ttsVoicesLoading" @click="previewVoice">
        {{ ttsPreviewing ? 'Stop' : 'Preview voice' }}
      </SButton>
    </div>
  </SettingsSection>

  <AccordionItem title="Keyboard Shortcuts" :icon="Keyboard" description="Quick reference for editor shortcuts">
    <div class="divide-y divide-border -m-3">
      <div v-for="s in shortcuts" :key="s.keys" class="flex items-center justify-between px-3 py-1.5">
        <span class="text-[12px] text-text-secondary">{{ s.desc }}</span>
        <kbd class="px-1.5 py-0.5 bg-surface-hover rounded-md text-[10px] font-mono text-text-muted border border-border">{{ s.keys }}</kbd>
      </div>
    </div>
  </AccordionItem>
</template>
