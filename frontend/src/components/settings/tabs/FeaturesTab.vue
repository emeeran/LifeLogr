<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { usePluginsStore } from '../../../stores/plugins'
import { useRemindersStore } from '../../../stores/reminders'
import { API_ORIGIN } from '../../../api/client'
import {
  Plus, Trash2, AlertTriangle, CheckCircle2,
  Loader, Volume2, Package, Power, PowerOff, Bell, Wrench, MonitorCheck
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import AccordionItem from '../shared/AccordionItem.vue'

interface TTSVoice {
  short_name: string
  locale: string
  gender: string
}

/** Parse "en-US-AvaNeural" into a human-friendly label. */
function voiceLabel(v: TTSVoice): string {
  const name = v.short_name.replace(/Neural$/, '').replace(/V2$/, '')
  // Extract the voice name part after locale (e.g. "en-US-Ava" → "Ava")
  const parts = name.split('-')
  // Locale is first 2 parts (e.g. "en-US"), the rest is the name
  const voiceName = parts.length > 2 ? parts.slice(2).join(' ') : parts[parts.length - 1]
  const gender = v.gender === 'Female' ? 'F' : v.gender === 'Male' ? 'M' : ''
  return `${voiceName} ${gender ? `(${gender})` : ''}`.trim()
}

/** Derive a display-friendly language name from locale code. */
function localeLabel(locale: string): string {
  const map: Record<string, string> = {
    'en-US': 'English (US)', 'en-GB': 'English (UK)', 'en-AU': 'English (AU)',
    'en-CA': 'English (CA)', 'en-IN': 'English (IN)', 'en-IE': 'English (IE)',
    'fr-FR': 'French', 'fr-CA': 'French (CA)', 'de-DE': 'German', 'de-AT': 'German (AT)',
    'es-ES': 'Spanish', 'es-MX': 'Spanish (MX)', 'pt-BR': 'Portuguese (BR)',
    'pt-PT': 'Portuguese (PT)', 'it-IT': 'Italian', 'nl-NL': 'Dutch',
    'pl-PL': 'Polish', 'ru-RU': 'Russian', 'ja-JP': 'Japanese',
    'zh-CN': 'Chinese (CN)', 'zh-TW': 'Chinese (TW)', 'ko-KR': 'Korean',
    'ar-SA': 'Arabic', 'hi-IN': 'Hindi', 'sv-SE': 'Swedish', 'da-DK': 'Danish',
    'fi-FI': 'Finnish', 'nb-NO': 'Norwegian', 'tr-TR': 'Turkish',
  }
  return map[locale] ?? locale
}

/** Group voices by locale for organized display. */
function voicesByLocale(voices: TTSVoice[]): Map<string, TTSVoice[]> {
  const groups = new Map<string, TTSVoice[]>()
  for (const v of voices) {
    const list = groups.get(v.locale) ?? []
    list.push(v)
    groups.set(v.locale, list)
  }
  return groups
}

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const pluginsStore = usePluginsStore()
const remindersStore = useRemindersStore()

// ── System Setup (Tauri desktop only) ──
const isTauri = !!(window as any).__TAURI_INTERNALS__
const depsStatus = ref<{ tesseract: boolean; ollama: boolean; gst_plugins_bad: boolean; all_installed: boolean } | null>(null)
const setupRunning = ref(false)
const setupOutput = ref('')

async function checkSystemDeps() {
  if (!isTauri) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    depsStatus.value = await invoke('check_deps') as any
  } catch { /* not running in Tauri */ }
}

async function runSystemSetup() {
  if (!isTauri) return
  setupRunning.value = true
  setupOutput.value = ''
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    setupOutput.value = await invoke('run_setup') as string
    emit('toast', 'success', 'System setup complete!')
    await checkSystemDeps()
  } catch (e: unknown) {
    setupOutput.value = errMsg(e)
    emit('toast', 'error', `Setup failed: ${errMsg(e)}`)
  } finally { setupRunning.value = false }
}

// ── TTS ──
const ttsSpeed = useLocalStorage<number>('diarium-tts-speed', 1.0)
const ttsVolume = useLocalStorage<number>('diarium-tts-volume', 100)
const ttsVoice = useLocalStorage<string>('tts-voice', 'en-US-AvaNeural')

const ttsVoices = ref<{ short_name: string; locale: string; gender: string }[]>([])
const ttsVoicesLoading = ref(false)

async function loadVoices() {
  ttsVoicesLoading.value = true
  try {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/voices`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    ttsVoices.value = await res.json()
  } catch { /* ignore */ }
  finally { ttsVoicesLoading.value = false }
}

// ── Plugins ──
const pluginForm = ref({ name: '', version: '', description: '', entry_point: '' })
const pluginInstalling = ref(false)

async function installPlugin() {
  if (!pluginForm.value.name || !pluginForm.value.entry_point) return
  pluginInstalling.value = true
  try { await pluginsStore.install(pluginForm.value); pluginForm.value = { name: '', version: '', description: '', entry_point: '' }; emit('toast', 'success', 'Plugin installed') }
  catch (e: unknown) { emit('toast', 'error', `Install failed: ${errMsg(e)}`) }
  finally { pluginInstalling.value = false }
}
async function togglePlugin(id: number, enabled: boolean) {
  try { enabled ? await pluginsStore.enable(id) : await pluginsStore.disable(id) }
  catch (e: unknown) { emit('toast', 'error', errMsg(e)) }
}
async function removePlugin(id: number) {
  try { await pluginsStore.uninstall(id); emit('toast', 'info', 'Plugin removed') }
  catch (e: unknown) { emit('toast', 'error', errMsg(e)) }
}

// ── Reminders ──
const reminderForm = ref({ title: '', message: '', reminder_time: '', days_of_week: 'mon,tue,wed,thu,fri,sat,sun' })
const reminderSaving = ref(false)

const dayLabels: Record<string, string> = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' }

async function createReminder() {
  if (!reminderForm.value.title || !reminderForm.value.reminder_time) return
  reminderSaving.value = true
  try {
    await remindersStore.create({
      title: reminderForm.value.title,
      message: reminderForm.value.message || undefined,
      reminder_time: reminderForm.value.reminder_time,
      days_of_week: reminderForm.value.days_of_week,
    })
    reminderForm.value = { title: '', message: '', reminder_time: '', days_of_week: 'mon,tue,wed,thu,fri,sat,sun' }
    emit('toast', 'success', 'Reminder created')
  } catch (e: unknown) { emit('toast', 'error', `Create failed: ${errMsg(e)}`) }
  finally { reminderSaving.value = false }
}

async function testReminder(id: number) {
  try { await remindersStore.testNotification(id); emit('toast', 'success', 'Notification sent') }
  catch (e: unknown) { emit('toast', 'error', `Test failed: ${errMsg(e)}`) }
}

async function deleteReminder(id: number) {
  try { await remindersStore.remove(id); emit('toast', 'info', 'Reminder deleted') }
  catch (e: unknown) { emit('toast', 'error', errMsg(e)) }
}

function resetTTSDefaults() {
  ttsVoice.value = 'en-US-AvaNeural'
  ttsSpeed.value = 1.0
  ttsVolume.value = 100
  emit('toast', 'success', 'TTS settings reset to defaults')
}

onMounted(() => {
  pluginsStore.fetchAll()
  remindersStore.fetchAll()
  loadVoices()
  checkSystemDeps()
})
</script>

<template>
  <!-- Read Aloud -->
  <SettingsSection title="Read Aloud" :icon="Volume2" description="Text-to-speech voice settings"
    reset-label="Reset" @reset="resetTTSDefaults">
    <SettingRow :icon="Volume2" label="Voice">
      <select v-model="ttsVoice" class="settings-select max-w-40" :disabled="ttsVoicesLoading">
        <option v-if="ttsVoicesLoading" disabled value="">Loading voices...</option>
        <template v-for="[locale, voices] in voicesByLocale(ttsVoices)" :key="locale">
          <optgroup :label="localeLabel(locale)">
            <option v-for="v in voices" :key="v.short_name" :value="v.short_name">
              {{ voiceLabel(v) }}
            </option>
          </optgroup>
        </template>
      </select>
    </SettingRow>
    <SettingRow indent :label="`Speed (${ttsSpeed.toFixed(1)}x)`">
      <input type="range" v-model.number="ttsSpeed" min="0.5" max="2.0" step="0.1" class="w-24 accent-accent" />
    </SettingRow>
    <SettingRow indent :label="`Volume (${ttsVolume}%)`">
      <input type="range" v-model.number="ttsVolume" min="0" max="100" step="5" class="w-24 accent-accent" />
    </SettingRow>
  </SettingsSection>

  <!-- Notifications -->
  <SettingsSection title="Notifications" :icon="Bell" description="Writing reminders and alerts">
    <div class="space-y-1.5">
      <input v-model="reminderForm.title" placeholder="Reminder title *"
        class="w-full settings-input py-1" />
      <div class="flex gap-1.5">
        <input v-model="reminderForm.message" placeholder="Message (optional)"
          class="flex-1 settings-input py-1" />
        <input v-model="reminderForm.reminder_time" type="time"
          class="settings-input w-20 py-1" />
      </div>
      <div class="flex items-center gap-1.5">
        <select v-model="reminderForm.days_of_week" class="flex-1 settings-select">
          <option value="mon,tue,wed,thu,fri,sat,sun">Every day</option>
          <option value="mon,tue,wed,thu,fri">Weekdays</option>
          <option value="sat,sun">Weekends</option>
        </select>
        <button @click="createReminder" :disabled="reminderSaving || !reminderForm.title || !reminderForm.reminder_time"
          class="flex items-center gap-1 px-2.5 py-1 rounded-md bg-accent text-white text-[11px] font-medium cursor-pointer hover:bg-accent-hover disabled:opacity-50 transition-colors">
          <Loader v-if="reminderSaving" :size="10" class="animate-spin" /> Add
        </button>
      </div>
    </div>
    <div v-if="remindersStore.reminders.length" class="space-y-1 border-t border-border pt-2">
      <div v-for="r in remindersStore.reminders" :key="r.id"
        class="flex items-center gap-2 px-2 py-1.5 rounded-md bg-surface-hover">
        <Bell :size="10" :class="r.is_active ? 'text-accent' : 'text-text-muted'" />
        <div class="flex-1 min-w-0">
          <div class="text-[12px] text-text-primary truncate">{{ r.title }}</div>
          <div class="text-[10px] text-text-muted">{{ r.reminder_time.slice(0,5) }} — {{ r.days_of_week.split(',').map(d => dayLabels[d] || d).join(', ') }}</div>
        </div>
        <button @click="testReminder(r.id)" class="p-0.5 rounded hover:bg-surface text-text-muted hover:text-accent cursor-pointer transition-colors" title="Test notification">
          <Volume2 :size="11" />
        </button>
        <button @click="deleteReminder(r.id)" class="p-0.5 rounded hover:bg-surface text-text-muted hover:text-danger cursor-pointer transition-colors" title="Delete reminder">
          <Trash2 :size="11" />
        </button>
      </div>
    </div>
    <div v-else class="text-center py-3 border-t border-border">
      <Bell :size="18" class="mx-auto text-text-muted mb-1" />
      <p class="text-[11px] text-text-secondary">No reminders set.</p>
      <p class="text-[10px] text-text-muted mt-0.5">Create one above to get writing prompts.</p>
    </div>
  </SettingsSection>

  <!-- Plugins -->
  <SettingsSection title="Plugins" :icon="Package" description="Extend DailyByte with plugins">
    <!-- Marketplace placeholder -->
    <div class="text-center py-4 border border-dashed border-border rounded-md mb-2">
      <Package :size="20" class="mx-auto text-text-muted mb-1" />
      <p class="text-[12px] text-text-secondary font-medium">Plugin Marketplace</p>
      <p class="text-[10px] text-text-muted mt-0.5">Browse and install community plugins — coming soon.</p>
    </div>
    <!-- Manual install -->
    <div class="space-y-1.5 border-t border-border pt-2">
      <p class="text-[10px] text-text-muted uppercase tracking-wide">Install manually</p>
      <div class="grid grid-cols-2 gap-1.5">
        <input v-model="pluginForm.name" placeholder="Name *" class="settings-input py-1" />
        <input v-model="pluginForm.entry_point" placeholder="module:function *" class="settings-input py-1" />
      </div>
      <div class="flex items-center gap-1.5">
        <input v-model="pluginForm.version" placeholder="Version" class="flex-1 settings-input py-1" />
        <button class="flex items-center gap-1 px-2.5 py-1 rounded-md bg-accent text-white text-[11px] font-medium cursor-pointer hover:bg-accent-hover disabled:opacity-50 transition-colors"
          :disabled="pluginInstalling || !pluginForm.name || !pluginForm.entry_point" @click="installPlugin">
          <Loader v-if="pluginInstalling" :size="10" class="animate-spin" /><Plus v-else :size="10" /> Install
        </button>
      </div>
    </div>
    <!-- Installed plugins -->
    <div v-for="p in pluginsStore.plugins" :key="p.id"
      class="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-surface-hover border border-border mt-1.5">
      <span class="text-[12px] font-medium text-text-primary flex-1">{{ p.name }}
        <span v-if="p.version" class="text-[10px] text-text-muted">v{{ p.version }}</span></span>
      <button class="p-0.5 rounded hover:bg-surface cursor-pointer transition-colors" :class="p.is_enabled ? 'text-green-400' : 'text-text-muted'"
        @click="togglePlugin(p.id, !p.is_enabled)" :title="p.is_enabled ? 'Disable plugin' : 'Enable plugin'">
        <PowerOff v-if="p.is_enabled" :size="12" /><Power v-else :size="12" />
      </button>
      <button class="p-0.5 rounded hover:bg-surface text-text-muted hover:text-danger cursor-pointer transition-colors" @click="removePlugin(p.id)" title="Remove plugin">
        <Trash2 :size="12" />
      </button>
    </div>
    <div v-if="!pluginsStore.plugins.length" class="text-center py-3 border-t border-border mt-2">
      <Package :size="18" class="mx-auto text-text-muted mb-1" />
      <p class="text-[11px] text-text-secondary">No plugins installed.</p>
      <p class="text-[10px] text-text-muted mt-0.5">Install one manually above or wait for the marketplace.</p>
    </div>
  </SettingsSection>

  <!-- System Setup (Tauri desktop only, collapsible) -->
  <AccordionItem v-if="isTauri" title="System Setup" :icon="Wrench" description="Check and install system dependencies">
    <div class="space-y-2">
      <div v-if="depsStatus === null" class="text-[11px] text-text-muted">Checking dependencies...</div>
      <div v-else-if="depsStatus.all_installed && depsStatus.gst_plugins_bad" class="flex items-center gap-1.5 text-[11px] text-green-400">
        <MonitorCheck :size="12" /> All system dependencies installed
      </div>
      <div v-else class="space-y-1.5">
        <div class="flex items-center gap-1.5 text-[11px]"
          :class="depsStatus.tesseract ? 'text-green-400' : 'text-red-400'">
          <CheckCircle2 v-if="depsStatus.tesseract" :size="11" />
          <AlertTriangle v-else :size="11" />
          Tesseract OCR {{ depsStatus.tesseract ? '(installed)' : '(missing)' }}
        </div>
        <div class="flex items-center gap-1.5 text-[11px]"
          :class="depsStatus.ollama ? 'text-green-400' : 'text-red-400'">
          <CheckCircle2 v-if="depsStatus.ollama" :size="11" />
          <AlertTriangle v-else :size="11" />
          Ollama AI {{ depsStatus.ollama ? '(installed)' : '(missing)' }}
        </div>
        <div class="flex items-center gap-1.5 text-[11px]"
          :class="depsStatus.gst_plugins_bad ? 'text-green-400' : 'text-yellow-400'">
          <CheckCircle2 v-if="depsStatus.gst_plugins_bad" :size="11" />
          <AlertTriangle v-else :size="11" />
          Audio Recording {{ depsStatus.gst_plugins_bad ? '(ready)' : '(needs gstreamer1.0-plugins-bad)' }}
        </div>
        <button class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50 mt-1"
          :disabled="setupRunning" @click="runSystemSetup">
          <Loader v-if="setupRunning" :size="11" class="animate-spin" />
          <Wrench v-else :size="11" />
          {{ setupRunning ? 'Installing...' : 'Install Missing Dependencies' }}
        </button>
      </div>
      <div v-if="setupOutput" class="p-2 rounded-md bg-black/30 text-[10px] font-mono text-green-300 max-h-32 overflow-y-auto whitespace-pre-wrap">
        {{ setupOutput }}
      </div>
    </div>
  </AccordionItem>
</template>
