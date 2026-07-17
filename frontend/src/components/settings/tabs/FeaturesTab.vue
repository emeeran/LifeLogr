<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useRemindersStore } from '../../../stores/reminders'
import { API_ORIGIN } from '../../../api/client'
import { ttsApi } from '../../../api/tts'
import type { ReminderResponse } from '../../../types'
import {
  Trash2, Pencil, AlertTriangle, CheckCircle2, X,
  Loader, Volume2, Bell, Wrench, MonitorCheck, Play, Heart,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import AccordionItem from '../shared/AccordionItem.vue'
import SButton from '../shared/SButton.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'

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

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()
function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const remindersStore = useRemindersStore()

// ── Memorial dedication title ──
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)

// ── System Setup (Tauri desktop only) ──
const isTauri = !!(window as any).__TAURI_INTERNALS__
const depsStatus = ref<{ ollama: boolean; gst_plugins_bad: boolean; all_installed: boolean } | null>(null)
const setupRunning = ref(false)
const setupOutput = ref('')

async function checkSystemDeps() {
  if (!isTauri) return
  try { const { invoke } = await import('@tauri-apps/api/core'); depsStatus.value = await invoke('check_deps') as any }
  catch { /* not running in Tauri */ }
}
async function runSystemSetup() {
  if (!isTauri) return
  setupRunning.value = true; setupOutput.value = ''
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    setupOutput.value = await invoke('run_setup') as string
    emit('toast', 'success', 'System setup complete!')
    await checkSystemDeps()
  } catch (e: unknown) { setupOutput.value = errMsg(e); emit('toast', 'error', `Setup failed: ${errMsg(e)}`) }
  finally { setupRunning.value = false }
}

// ── TTS ──
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
  emit('toast', 'success', 'TTS settings reset to defaults')
}

// ── Reminders ──
const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const dayLabels: Record<string, string> = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' }
const PRESETS: { label: string; days: string }[] = [
  { label: 'Every day', days: 'mon,tue,wed,thu,fri,sat,sun' },
  { label: 'Weekdays', days: 'mon,tue,wed,thu,fri' },
  { label: 'Weekends', days: 'sat,sun' },
  { label: 'Custom…', days: '' },
]

const reminderForm = reactive({ title: '', message: '', reminder_time: '', days_of_week: 'mon,tue,wed,thu,fri,sat,sun' })
const reminderSaving = ref(false)
const editingId = ref<number | null>(null)

const formError = computed(() => {
  if (!reminderForm.title.trim()) return ''
  if (!reminderForm.reminder_time) return ''
  if (reminderForm.days_of_week === '' && customPickerActive.value) {
    if (selectedDays.value.size === 0) return 'Pick at least one day'
  }
  return ''
})

// Custom day picker state
const customPickerActive = ref(false)
const selectedDays = ref(new Set<string>())

function onPresetChange(e: Event) {
  const val = (e.target as HTMLSelectElement).value
  const preset = PRESETS.find(p => p.label === val)
  if (!preset) return
  if (preset.days === '') {
    customPickerActive.value = true
    if (selectedDays.value.size === 0) reminderForm.days_of_week = ''
  } else {
    customPickerActive.value = false
    reminderForm.days_of_week = preset.days
    selectedDays.value = new Set(preset.days.split(','))
  }
}
function toggleDay(d: string) {
  const s = new Set(selectedDays.value)
  s.has(d) ? s.delete(d) : s.add(d)
  selectedDays.value = s
  reminderForm.days_of_week = DAY_KEYS.filter(k => s.has(k)).join(',')
}

function startEdit(r: ReminderResponse) {
  editingId.value = r.id
  reminderForm.title = r.title
  reminderForm.message = r.message ?? ''
  reminderForm.reminder_time = r.reminder_time
  reminderForm.days_of_week = r.days_of_week
  const days = r.days_of_week.split(',').filter(Boolean)
  selectedDays.value = new Set(days)
  customPickerActive.value = !PRESETS.some(p => p.days === r.days_of_week)
}
function cancelEdit() { editingId.value = null; resetForm() }
function resetForm() {
  reminderForm.title = ''; reminderForm.message = ''; reminderForm.reminder_time = ''
  reminderForm.days_of_week = 'mon,tue,wed,thu,fri,sat,sun'
  selectedDays.value = new Set(); customPickerActive.value = false
}

async function submitReminder() {
  if (formError.value || !reminderForm.title.trim() || !reminderForm.reminder_time) return
  reminderSaving.value = true
  try {
    const payload = {
      title: reminderForm.title,
      message: reminderForm.message || undefined,
      reminder_time: reminderForm.reminder_time,
      days_of_week: reminderForm.days_of_week || 'mon,tue,wed,thu,fri,sat,sun',
    }
    if (editingId.value !== null) {
      await remindersStore.update(editingId.value, payload)
      emit('toast', 'success', 'Reminder updated')
      editingId.value = null
    } else {
      await remindersStore.create(payload)
      emit('toast', 'success', 'Reminder created')
    }
    resetForm()
  } catch (e: unknown) { emit('toast', 'error', `Save failed: ${errMsg(e)}`) }
  finally { reminderSaving.value = false }
}

async function testReminder(id: number) {
  try { await remindersStore.testNotification(id); emit('toast', 'success', 'Notification sent') }
  catch (e: unknown) { emit('toast', 'error', `Test failed: ${errMsg(e)}`) }
}
async function deleteReminder(id: number) {
  try { await remindersStore.remove(id); emit('toast', 'info', 'Reminder deleted'); if (editingId.value === id) cancelEdit() }
  catch (e: unknown) { emit('toast', 'error', errMsg(e)) }
}

/** Human-readable summary of a reminder's day selection. */
function daysSummary(days: string): string {
  const list = days.split(',').filter(Boolean)
  const preset = PRESETS.find(p => p.days === list.join(','))
  if (preset) return preset.label
  return list.map(d => dayLabels[d] ?? d).join(', ')
}

onMounted(() => { remindersStore.fetchAll(); loadVoices(); checkSystemDeps() })
</script>

<template>
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
      description="Lower for a deeper, warmer voice; raise for brighter. Applies to journals, notes and email.">
      <input type="range" v-model.number="ttsPitch" min="-40" max="40" step="5" class="w-28 accent-accent" />
    </SettingRow>
    <div class="pl-[31px]">
      <SButton variant="outline" size="xs" :icon="ttsPreviewing ? X : Play" :disabled="ttsVoicesLoading" @click="previewVoice">
        <Loader v-if="false" :size="11" class="animate-spin" />
        {{ ttsPreviewing ? 'Stop' : 'Preview voice' }}
      </SButton>
    </div>
  </SettingsSection>

  <SettingsSection title="Notifications" :icon="Bell" description="Writing reminders and alerts" setting-key="Reminders">
    <!-- Create / edit form -->
    <div class="space-y-1.5 pb-1">
      <input v-model="reminderForm.title" placeholder="Reminder title *" class="w-full settings-input py-1" />
      <div class="flex gap-1.5">
        <input v-model="reminderForm.message" placeholder="Message (optional)" class="flex-1 settings-input py-1" />
        <input v-model="reminderForm.reminder_time" type="time" class="settings-input w-20 py-1" />
      </div>
      <div class="flex items-center gap-1.5">
        <select class="flex-1 settings-select" @change="onPresetChange">
          <option value="" disabled>Select days…</option>
          <option v-for="p in PRESETS" :key="p.label" :value="p.label">{{ p.label }}</option>
        </select>
        <SButton variant="primary" :disabled="reminderSaving || !!formError || !reminderForm.title || !reminderForm.reminder_time" @click="submitReminder">
          <Loader v-if="reminderSaving" :size="11" class="animate-spin" />
          {{ editingId !== null ? 'Update' : 'Add' }}
        </SButton>
        <SButton v-if="editingId !== null" variant="ghost" @click="cancelEdit">Cancel</SButton>
      </div>
      <!-- Custom day picker -->
      <div v-if="customPickerActive" class="flex items-center gap-1 pl-1">
        <button v-for="d in DAY_KEYS" :key="d" type="button"
          class="w-7 h-7 rounded-md text-[10px] font-medium transition-colors cursor-pointer"
          :class="selectedDays.has(d) ? 'bg-accent text-white' : 'bg-surface-hover text-text-muted hover:text-text-primary'"
          :aria-pressed="selectedDays.has(d)"
          @click="toggleDay(d)">{{ dayLabels[d] }}</button>
      </div>
      <p v-if="formError" class="text-[11px] text-danger">{{ formError }}</p>
    </div>

    <div v-if="remindersStore.reminders.length" class="space-y-1 border-t border-border pt-2">
      <div v-for="r in remindersStore.reminders" :key="r.id"
        class="flex items-center gap-2 px-2 py-1.5 rounded-md bg-surface-hover">
        <Bell :size="11" :class="r.is_active ? 'text-accent' : 'text-text-muted'" aria-hidden="true" />
        <div class="flex-1 min-w-0">
          <div class="text-[12px] text-text-primary truncate">{{ r.title }}</div>
          <div class="text-[10px] text-text-muted">{{ r.reminder_time.slice(0,5) }} — {{ daysSummary(r.days_of_week) }}</div>
        </div>
        <SButton variant="ghost" size="xs" :icon="Pencil" title="Edit reminder" @click="startEdit(r)" />
        <SButton variant="ghost" size="xs" :icon="Volume2" title="Test notification" @click="testReminder(r.id)" />
        <SButton variant="ghost" size="xs" :icon="Trash2" title="Delete reminder" class="!text-text-muted hover:!text-danger" @click="deleteReminder(r.id)" />
      </div>
    </div>
    <div v-else class="text-center py-3 border-t border-border">
      <Bell :size="18" class="mx-auto text-text-muted mb-1" />
      <p class="text-[11px] text-text-secondary">No reminders set.</p>
      <p class="text-[10px] text-text-muted mt-0.5">Create one above to get writing prompts.</p>
    </div>
  </SettingsSection>

  <SettingsSection title="Memorial" :icon="Heart" description="Dedication tribute on the Dedication tab" setting-key="Memorial title">
    <SettingRow :icon="Heart" label="Memorial title"
      description="Show “Ever in memory of you” above the portrait, with a gentle flash each time you open the Dedication.">
      <ToggleSwitch v-model="memorialTitle" />
    </SettingRow>
  </SettingsSection>

  <AccordionItem v-if="isTauri" title="System Setup" :icon="Wrench" description="Check and install system dependencies">
    <div class="space-y-2">
      <div v-if="depsStatus === null" class="text-[11px] text-text-muted">Checking dependencies...</div>
      <div v-else-if="depsStatus.all_installed && depsStatus.gst_plugins_bad" class="flex items-center gap-1.5 text-[11px] text-green-400">
        <MonitorCheck :size="12" /> All system dependencies installed
      </div>
      <div v-else class="space-y-1.5">
        <div class="flex items-center gap-1.5 text-[11px]" :class="depsStatus.ollama ? 'text-green-400' : 'text-red-400'">
          <CheckCircle2 v-if="depsStatus.ollama" :size="11" /><AlertTriangle v-else :size="11" />
          Ollama AI {{ depsStatus.ollama ? '(installed)' : '(missing)' }}
        </div>
        <div class="flex items-center gap-1.5 text-[11px]" :class="depsStatus.gst_plugins_bad ? 'text-green-400' : 'text-yellow-400'">
          <CheckCircle2 v-if="depsStatus.gst_plugins_bad" :size="11" /><AlertTriangle v-else :size="11" />
          Audio Recording {{ depsStatus.gst_plugins_bad ? '(ready)' : '(needs gstreamer1.0-plugins-bad)' }}
        </div>
        <SButton variant="primary" :disabled="setupRunning" :icon="Wrench" class="mt-1" @click="runSystemSetup">
          <Loader v-if="setupRunning" :size="12" class="animate-spin" />
          {{ setupRunning ? 'Installing…' : 'Install Missing Dependencies' }}
        </SButton>
      </div>
      <div v-if="setupOutput" class="p-2 rounded-md bg-black/30 text-[10px] font-mono text-green-300 max-h-32 overflow-y-auto whitespace-pre-wrap">{{ setupOutput }}</div>
    </div>
  </AccordionItem>
</template>
