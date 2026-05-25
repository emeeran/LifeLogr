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
  } finally {
    setupRunning.value = false
  }
}

// ── 6. TTS speed/volume ──
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
  } catch { /* ignore -- voices will show as empty */ }
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

// ── 9. Reminders ──
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
  try {
    await remindersStore.testNotification(id)
    emit('toast', 'success', 'Notification sent')
  } catch (e: unknown) { emit('toast', 'error', `Test failed: ${errMsg(e)}`) }
}

async function deleteReminder(id: number) {
  try {
    await remindersStore.remove(id)
    emit('toast', 'info', 'Reminder deleted')
  } catch (e: unknown) { emit('toast', 'error', errMsg(e)) }
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
  <!-- Read Aloud (TTS) -->
  <section>
    <div class="flex items-center justify-between mb-1">
      <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1">
        <Volume2 :size="11" /> Read Aloud
      </h3>
      <button @click="resetTTSDefaults"
        class="text-[9px] text-text-muted hover:text-accent cursor-pointer transition-colors">Reset defaults</button>
    </div>
    <div class="bg-surface rounded p-2 border border-border space-y-1.5">
      <div class="flex items-center gap-2">
        <Volume2 :size="11" class="text-text-muted" />
        <span class="text-[11px] text-text-secondary flex-1">Voice</span>
        <select v-model="ttsVoice"
          class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]"
          :disabled="ttsVoicesLoading">
          <option v-for="v in ttsVoices.filter(v => v.locale.startsWith('en'))" :key="v.short_name" :value="v.short_name">
            {{ v.short_name.replace('en-', '').replace('Neural', '') }}
          </option>
          <optgroup v-if="ttsVoices.some(v => !v.locale.startsWith('en'))" label="Other languages">
            <option v-for="v in ttsVoices.filter(v => !v.locale.startsWith('en'))" :key="v.short_name" :value="v.short_name">
              {{ v.short_name }}
            </option>
          </optgroup>
        </select>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-text-secondary flex-1">Speed ({{ ttsSpeed.toFixed(1) }}x)</span>
        <input type="range" v-model.number="ttsSpeed" min="0.5" max="2.0" step="0.1" class="w-20 accent-accent" />
      </div>
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-text-secondary flex-1">Volume ({{ ttsVolume }}%)</span>
        <input type="range" v-model.number="ttsVolume" min="0" max="100" step="5" class="w-20 accent-accent" />
      </div>
    </div>
  </section>

  <!-- Notifications -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Bell :size="11" /> Notifications
    </h3>
    <div class="bg-surface rounded p-2 border border-border space-y-2">
      <!-- Quick add -->
      <div class="space-y-1">
        <input v-model="reminderForm.title" placeholder="Reminder title *"
          class="w-full bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary" />
        <div class="flex gap-1">
          <input v-model="reminderForm.message" placeholder="Message (optional)"
            class="flex-1 bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary" />
          <input v-model="reminderForm.reminder_time" type="time"
            class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary w-[70px]" />
        </div>
        <div class="flex items-center gap-1">
          <select v-model="reminderForm.days_of_week"
            class="flex-1 bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary">
            <option value="mon,tue,wed,thu,fri,sat,sun">Every day</option>
            <option value="mon,tue,wed,thu,fri">Weekdays</option>
            <option value="sat,sun">Weekends</option>
          </select>
          <button @click="createReminder" :disabled="reminderSaving || !reminderForm.title || !reminderForm.reminder_time"
            class="flex items-center gap-1 px-2 py-0.5 rounded bg-accent text-white text-[10px] cursor-pointer hover:bg-accent-hover disabled:opacity-50">
            <Loader v-if="reminderSaving" :size="9" class="animate-spin" /> Add
          </button>
        </div>
      </div>
      <!-- Existing reminders -->
      <div v-if="remindersStore.reminders.length" class="space-y-0.5 border-t border-border pt-1.5">
        <div v-for="r in remindersStore.reminders" :key="r.id"
          class="flex items-center gap-1.5 px-1.5 py-1 rounded bg-surface-hover">
          <Bell :size="9" :class="r.is_active ? 'text-accent' : 'text-text-muted'" />
          <div class="flex-1 min-w-0">
            <div class="text-[11px] text-text-primary truncate">{{ r.title }}</div>
            <div class="text-[9px] text-text-muted">{{ r.reminder_time.slice(0,5) }} — {{ r.days_of_week.split(',').map(d => dayLabels[d] || d).join(', ') }}</div>
          </div>
          <button @click="testReminder(r.id)" class="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-accent cursor-pointer" title="Test">
            <Volume2 :size="10" />
          </button>
          <button @click="deleteReminder(r.id)" class="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-danger cursor-pointer" title="Delete">
            <Trash2 :size="10" />
          </button>
        </div>
      </div>
      <div v-else class="text-[10px] text-text-muted text-center py-1">No reminders set.</div>
    </div>
  </section>

  <!-- Plugins -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Package :size="11" /> Plugins
    </h3>
    <div class="bg-surface rounded p-2 border border-border space-y-2">
      <!-- Marketplace placeholder -->
      <div class="text-center py-3 border border-dashed border-border rounded">
        <Package :size="20" class="mx-auto text-text-muted mb-1" />
        <div class="text-[11px] text-text-secondary font-medium">Plugin Marketplace</div>
        <div class="text-[9px] text-text-muted mt-0.5">Browse and install community plugins -- coming soon.</div>
      </div>
      <!-- Manual install -->
      <div class="space-y-1 border-t border-border pt-1.5">
        <div class="text-[10px] text-text-muted">Install manually</div>
        <div class="grid grid-cols-2 gap-1">
          <input v-model="pluginForm.name" placeholder="Name *" class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary" />
          <input v-model="pluginForm.entry_point" placeholder="module:function *" class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary" />
        </div>
        <div class="flex items-center gap-1">
          <input v-model="pluginForm.version" placeholder="Version" class="flex-1 bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary" />
          <button class="flex items-center gap-0.5 px-2 py-0.5 rounded bg-accent text-white text-[10px] cursor-pointer hover:bg-accent-hover disabled:opacity-50"
            :disabled="pluginInstalling || !pluginForm.name || !pluginForm.entry_point" @click="installPlugin">
            <Loader v-if="pluginInstalling" :size="9" class="animate-spin" /><Plus v-else :size="9" /> Install
          </button>
        </div>
      </div>
      <div v-for="p in pluginsStore.plugins" :key="p.id"
        class="bg-surface-hover rounded px-2 py-1 border border-border flex items-center gap-2">
        <span class="text-[11px] font-medium text-text-primary flex-1">{{ p.name }}
          <span v-if="p.version" class="text-[9px] text-text-muted">v{{ p.version }}</span></span>
        <button class="p-0.5 rounded hover:bg-surface-hover cursor-pointer" :class="p.is_enabled ? 'text-green-400' : 'text-text-muted'"
          @click="togglePlugin(p.id, !p.is_enabled)">
          <PowerOff v-if="p.is_enabled" :size="11" /><Power v-else :size="11" />
        </button>
        <button class="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-danger cursor-pointer" @click="removePlugin(p.id)">
          <Trash2 :size="11" />
        </button>
      </div>
      <div v-if="!pluginsStore.plugins.length" class="text-[10px] text-text-muted text-center">No plugins installed.</div>
    </div>
  </section>

  <!-- System Setup (Tauri desktop only) -->
  <section v-if="isTauri">
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Wrench :size="11" /> System Setup
    </h3>
    <div class="bg-surface rounded p-2 border border-border space-y-1.5">
      <div v-if="depsStatus === null" class="text-[10px] text-text-muted">Checking dependencies...</div>
      <div v-else-if="depsStatus.all_installed && depsStatus.gst_plugins_bad" class="flex items-center gap-1 text-[10px] text-green-400">
        <MonitorCheck :size="11" /> All system dependencies installed
      </div>
      <div v-else class="space-y-1">
        <div class="flex items-center gap-1 text-[10px]"
          :class="depsStatus.tesseract ? 'text-green-400' : 'text-red-400'">
          <CheckCircle2 v-if="depsStatus.tesseract" :size="10" />
          <AlertTriangle v-else :size="10" />
          Tesseract OCR {{ depsStatus.tesseract ? '(installed)' : '(missing)' }}
        </div>
        <div class="flex items-center gap-1 text-[10px]"
          :class="depsStatus.ollama ? 'text-green-400' : 'text-red-400'">
          <CheckCircle2 v-if="depsStatus.ollama" :size="10" />
          <AlertTriangle v-else :size="10" />
          Ollama AI {{ depsStatus.ollama ? '(installed)' : '(missing)' }}
        </div>
        <div class="flex items-center gap-1 text-[10px]"
          :class="depsStatus.gst_plugins_bad ? 'text-green-400' : 'text-yellow-400'">
          <CheckCircle2 v-if="depsStatus.gst_plugins_bad" :size="10" />
          <AlertTriangle v-else :size="10" />
          Audio Recording {{ depsStatus.gst_plugins_bad ? '(ready)' : '(needs gstreamer1.0-plugins-bad)' }}
        </div>
        <button class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50 mt-1"
          :disabled="setupRunning" @click="runSystemSetup">
          <Loader v-if="setupRunning" :size="10" class="animate-spin" />
          <Wrench v-else :size="10" />
          {{ setupRunning ? 'Installing...' : 'Install Missing Dependencies' }}
        </button>
      </div>
      <div v-if="setupOutput" class="mt-1 p-1.5 rounded bg-black/30 text-[9px] font-mono text-green-300 max-h-32 overflow-y-auto whitespace-pre-wrap">
        {{ setupOutput }}
      </div>
    </div>
  </section>
</template>
