<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useBackupStore } from '../../stores/backup'
import { backupApi } from '../../api/backup'
import { entriesApi } from '../../api/entries'
import { getThemes, pullModel } from '../../api/ai'
import type { ThemeInsight } from '../../types'
import { useSyncStore } from '../../stores/sync'
import { useEntriesStore } from '../../stores/entries'
import { usePluginsStore } from '../../stores/plugins'
import { exportHtml, getExportPdfUrl } from '../../api/export'
import { useLocalStorage } from '@vueuse/core'
import { API_ORIGIN } from '../../api/client'
import { useUiStore } from '../../stores/ui'
import { useSearchStore } from '../../stores/search'
import { useRemindersStore } from '../../stores/reminders'
import { getSettings, updateSettings, getOllamaModels } from '../../api/settings'
import type { AppSettings, AIModelInfo } from '../../api/settings'
import {
  Cloud, RefreshCw, RotateCcw, Plus, Trash2,
  Download, Upload, AlertTriangle, CheckCircle2, X, Info,
  ArrowUp, ArrowDown, Power, PowerOff, Loader, FileUp, MapPin, Database, Copy, Volume2, LayoutTemplate,
  Wrench, MonitorCheck, Sparkles, Brain, Download as DownloadIcon,
  Sun, Moon, Type, Search, Bell, Keyboard, Info as InfoIcon, Package,
  HardDrive, Sliders, Eye, Clock
} from 'lucide-vue-next'
import ConfirmDialog from '../common/ConfirmDialog.vue'
import { useTemplatesStore } from '../../stores/templates'

const backup = useBackupStore()
const syncStore = useSyncStore()
const entriesStore = useEntriesStore()
const pluginsStore = usePluginsStore()
const templatesStore = useTemplatesStore()
const ui = useUiStore()
const searchStore = useSearchStore()
const remindersStore = useRemindersStore()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

// ── Tab navigation ──
const activeTab = useLocalStorage<string>('diarium-settings-tab', 'general')
const tabs = [
  { id: 'general', label: 'General', icon: Sliders },
  { id: 'ai', label: 'AI', icon: Brain },
  { id: 'data', label: 'Data', icon: HardDrive },
  { id: 'features', label: 'Features', icon: Sparkles },
  { id: 'about', label: 'About', icon: Info },
] as const

// ── System Setup (Tauri desktop only) ──
const isTauri = !!(window as any).__TAURI_INTERNALS__
const depsStatus = ref<{ tesseract: boolean; ollama: boolean; all_installed: boolean } | null>(null)
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
    showToast('success', 'System setup complete!')
    await checkSystemDeps()
  } catch (e: unknown) {
    setupOutput.value = errMsg(e)
    showToast('error', `Setup failed: ${errMsg(e)}`)
  } finally {
    setupRunning.value = false
  }
}

// ── Preferences ──
const autoGeotag = useLocalStorage<boolean>('diarium-auto-geotag', false)
const ttsVoice = useLocalStorage<string>('tts-voice', 'en-US-AvaNeural')
const defaultTemplateId = useLocalStorage<number | null>('diarium-default-template', null)

// ── 1. Appearance ──
const fontOptions = [
  { value: 'system-ui', label: 'System UI' },
  { value: 'Georgia, serif', label: 'Georgia (Serif)' },
  { value: "'Merriweather', serif", label: 'Merriweather' },
  { value: "'Noto Serif', serif", label: 'Noto Serif' },
  { value: "monospace", label: 'Monospace' },
]

// ── 3. Editor ──
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

// ── 6. TTS speed/volume ──
const ttsSpeed = useLocalStorage<number>('diarium-tts-speed', 1.0)
const ttsVolume = useLocalStorage<number>('diarium-tts-volume', 100)

// ── 2. AI Configuration ──
const appSettings = ref<AppSettings | null>(null)
const ollamaModels = ref<AIModelInfo[]>([])
const settingsLoading = ref(false)
const aiSaving = ref(false)

async function loadAppSettings() {
  settingsLoading.value = true
  try {
    appSettings.value = await getSettings()
  } catch { /* ignore */ }
  finally { settingsLoading.value = false }
}

async function loadOllamaModels() {
  try { ollamaModels.value = await getOllamaModels() } catch { /* ignore */ }
}

async function saveAISettings() {
  if (!appSettings.value) return
  aiSaving.value = true
  try {
    await updateSettings({ ai: appSettings.value.ai })
    showToast('success', 'AI settings saved')
  } catch (e: unknown) {
    showToast('error', `Save failed: ${errMsg(e)}`)
  } finally {
    aiSaving.value = false
  }
}

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

// ── Import / Export ──
const fileImporting = ref(false)
const fileImportInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)

async function handleFileImport(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  fileImporting.value = true
  try {
    const r = await entriesApi.importFile(file)
    entriesStore.refreshAll()
    showToast('success', `Imported ${r.imported} entries`)
  } catch (e: unknown) { showToast('error', `Import failed: ${errMsg(e)}`) }
  finally { fileImporting.value = false; if (fileImportInput.value) fileImportInput.value.value = '' }
}

async function handleImport(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  importing.value = true
  try { const r = await backupApi.importLocal(file); entriesStore.refreshAll(); showToast('success', `Restored — ${r.restored.join(', ')}`) }
  catch (e: unknown) { showToast('error', `Import failed: ${errMsg(e)}`) }
  finally { importing.value = false; if (importFileInput.value) importFileInput.value.value = '' }
}

const exportRange = ref<'all' | 'range'>('all')
const exportFrom = ref('')
const exportTo = ref('')
const exportingHtml = ref(false)
const deduplicating = ref(false)

function downloadMarkdown() {
  const url = exportRange.value === 'range' && exportFrom.value && exportTo.value
    ? entriesApi.exportMarkdownUrl(exportFrom.value, exportTo.value)
    : entriesApi.exportMarkdownUrl()
  Object.assign(document.createElement('a'), { href: url, download: 'diarium-export.zip' }).click()
}

async function downloadHtmlExport() {
  exportingHtml.value = true
  try {
    const html = await exportHtml(exportFrom.value || undefined, exportTo.value || undefined)
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    Object.assign(document.createElement('a'), { href: url, download: 'diary-export.html' }).click()
    URL.revokeObjectURL(url)
  } catch (e: unknown) { showToast('error', `HTML export failed: ${errMsg(e)}`) }
  finally { exportingHtml.value = false }
}

function downloadPdfExport() {
  const url = getExportPdfUrl(exportFrom.value || undefined, exportTo.value || undefined)
  Object.assign(document.createElement('a'), { href: url, download: 'diary-export.pdf' }).click()
}

function downloadExport() {
  Object.assign(document.createElement('a'), { href: backupApi.exportLocal(), download: '' }).click()
}

async function handleDeduplicate() {
  deduplicating.value = true
  try {
    const r = await entriesApi.deduplicate()
    if (r.duplicates_removed === 0) {
      showToast('info', 'No duplicates found')
    } else {
      showToast('success', `Removed ${r.duplicates_removed} duplicate${r.duplicates_removed > 1 ? 's' : ''} across ${r.groups_found} group${r.groups_found > 1 ? 's' : ''}`)
    }
  } catch (e: unknown) { showToast('error', `Deduplicate failed: ${errMsg(e)}`) }
  finally { deduplicating.value = false }
}

// ── Cloud Backup ──
const showCreate = ref(false)
const newProvider = ref('webdav')
const newCredentials = ref<Record<string, string>>({})
const newSchedule = ref('')
const testResult = ref<{ configId: number; success: boolean; message: string } | null>(null)
const backingUp = ref<number | null>(null)
const restoring = ref<number | null>(null)
const deleteConfirm = ref<number | null>(null)
const restoreConfirm = ref<{ configId: number; provider: string } | null>(null)

const providerFields: Record<string, { label: string; placeholder: string }[]> = {
  webdav: [
    { label: 'URL', placeholder: 'https://dav.example.com/remote.php/dav/files/' },
    { label: 'Username', placeholder: 'user' },
    { label: 'Password', placeholder: 'password or app token' },
  ],
  google_drive: [
    { label: 'Client ID', placeholder: 'xxxx.apps.googleusercontent.com' },
    { label: 'Client Secret', placeholder: 'GOCSPX-xxxx' },
    { label: 'Refresh Token', placeholder: '1//xxxx' },
  ],
  onedrive: [
    { label: 'Client ID', placeholder: 'xxxx-xxxx-xxxx' },
    { label: 'Client Secret', placeholder: 'xxxx~xxxx' },
    { label: 'Refresh Token', placeholder: '0.ARoxxxx' },
  ],
  dropbox: [{ label: 'Access Token', placeholder: 'sl.xxxxx' }],
  nas: [
    { label: 'Host', placeholder: '192.168.1.100' },
    { label: 'Share Path', placeholder: '/volume1/backup' },
    { label: 'Username', placeholder: 'admin' },
    { label: 'Password', placeholder: 'password' },
  ],
}
const currentFields = computed(() => providerFields[newProvider.value] ?? [])

function resetNewCredentials() {
  const creds: Record<string, string> = {}
  for (const f of currentFields.value) creds[f.label.toLowerCase().replace(/\s+/g, '_')] = ''
  newCredentials.value = creds
}

const showManualGoogleFields = ref(false)

async function startGoogleDriveAuth() {
  try {
    const res = await backupApi.getGoogleDriveAuthUrl()
    window.open(res.auth_url, '_blank')
    showToast('info', 'Opening Google Authentication in browser...')
    showCreate.value = false
    setTimeout(async () => {
      await backup.fetchConfigs()
    }, 6000)
  } catch (e: unknown) {
    showToast('error', `Google auth initiation failed: ${errMsg(e)}`)
  }
}

function openCreateForm() {
  newProvider.value = 'webdav'; showManualGoogleFields.value = false; resetNewCredentials(); newSchedule.value = ''; showCreate.value = true
}

async function createConfig() {
  const filtered: Record<string, string> = {}
  for (const [k, v] of Object.entries(newCredentials.value)) if (v.trim()) filtered[k] = v
  await backupApi.createConfig({ provider: newProvider.value, credentials: filtered, schedule_cron: newSchedule.value || null })
  showCreate.value = false
  await backup.fetchConfigs()
}

async function testConn(id: number) {
  testResult.value = null
  try { testResult.value = { configId: id, ...await backupApi.testConnection(id) } }
  catch (e: unknown) { testResult.value = { configId: id, success: false, message: errMsg(e) } }
}

async function runBackup(configId: number) {
  backingUp.value = configId; testResult.value = null
  try {
    const snap = await backup.runBackup(configId)
    showToast(snap.status === 'completed' ? 'success' : 'error',
      snap.status === 'completed' ? `Backup done — ${snap.entries_synced}e ${snap.media_synced}m` : `Backup failed: ${snap.error_message ?? 'unknown'}`)
  } catch (e: unknown) { showToast('error', `Backup failed: ${errMsg(e)}`) }
  finally { backingUp.value = null }
}

async function confirmRestore() {
  if (!restoreConfirm.value) return
  const { configId, provider } = restoreConfirm.value; restoreConfirm.value = null; restoring.value = configId
  try {
    const r = await backup.restore(configId)
    showToast('success', `Restored from ${provider.replace('_', ' ')} — ${(r as any).entries_restored ?? 0}e ${(r as any).media_restored ?? 0}m`)
  } catch (e: unknown) { showToast('error', `Restore failed: ${errMsg(e)}`) }
  finally { restoring.value = null }
}

async function confirmDelete() {
  if (!deleteConfirm.value) return
  try { await backup.deleteConfig(deleteConfirm.value); showToast('info', 'Config deleted') }
  catch (e: unknown) { showToast('error', `Delete failed: ${errMsg(e)}`) }
  finally { deleteConfirm.value = null }
}

// ── Sync ──
const syncPushing = ref(false)
const syncPulling = ref(false)

async function handleSyncPush() {
  syncPushing.value = true
  try { await syncStore.push('local_file'); showToast('success', 'Push done') }
  catch (e: unknown) { showToast('error', `Push failed: ${errMsg(e)}`) }
  finally { syncPushing.value = false }
}
async function handleSyncPull() {
  syncPulling.value = true
  try { await syncStore.pull('local_file'); showToast('success', 'Pull done') }
  catch (e: unknown) { showToast('error', `Pull failed: ${errMsg(e)}`) }
  finally { syncPulling.value = false }
}
async function handleSyncFlush() {
  try { await syncStore.flush(); showToast('success', 'Queue flushed'); syncStore.fetchStatus() }
  catch (e: unknown) { showToast('error', `Flush failed: ${errMsg(e)}`) }
}

// ── Plugins ──
const pluginForm = ref({ name: '', version: '', description: '', entry_point: '' })
const pluginInstalling = ref(false)

async function installPlugin() {
  if (!pluginForm.value.name || !pluginForm.value.entry_point) return
  pluginInstalling.value = true
  try { await pluginsStore.install(pluginForm.value); pluginForm.value = { name: '', version: '', description: '', entry_point: '' }; showToast('success', 'Plugin installed') }
  catch (e: unknown) { showToast('error', `Install failed: ${errMsg(e)}`) }
  finally { pluginInstalling.value = false }
}
async function togglePlugin(id: number, enabled: boolean) {
  try { enabled ? await pluginsStore.enable(id) : await pluginsStore.disable(id) }
  catch (e: unknown) { showToast('error', errMsg(e)) }
}
async function removePlugin(id: number) {
  try { await pluginsStore.uninstall(id); showToast('info', 'Plugin removed') }
  catch (e: unknown) { showToast('error', errMsg(e)) }
}

// ── Reset ──
const showResetConfirm = ref(false)
const resetConfirmText = ref('')
const resetting = ref(false)

async function handleReset() {
  resetting.value = true
  try { await entriesApi.resetDatabase(); entriesStore.refreshAll(); showToast('success', 'Database cleared'); showResetConfirm.value = false; resetConfirmText.value = '' }
  catch (e: unknown) { showToast('error', `Reset failed: ${errMsg(e)}`) }
  finally { resetting.value = false }
}

const ttsVoices = ref<{ short_name: string; locale: string; gender: string }[]>([])
const ttsVoicesLoading = ref(false)

async function loadVoices() {
  ttsVoicesLoading.value = true
  try {
    const res = await fetch(`${API_ORIGIN}/api/v1/tts/voices`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    ttsVoices.value = await res.json()
  } catch { /* ignore — voices will show as empty */ }
  finally { ttsVoicesLoading.value = false }
}

// ── AI Themes & Insights ──
const themesMonths = ref(6)
const themes = ref<ThemeInsight[]>([])
const themesLoading = ref(false)

async function fetchThemes() {
  themesLoading.value = true
  try {
    const res = await getThemes(themesMonths.value)
    themes.value = res.themes
  } catch (e: unknown) { showToast('error', `Themes failed: ${errMsg(e)}`) }
  finally { themesLoading.value = false }
}

// ── Pull AI Model ──
const pullModelName = ref('')
const pulling = ref(false)
const pullStatus = ref('')

async function handlePullModel() {
  if (!pullModelName.value.trim()) return
  pulling.value = true
  pullStatus.value = 'Pulling...'
  try {
    await pullModel(pullModelName.value.trim())
    pullStatus.value = `Pull started for ${pullModelName.value.trim()}`
    showToast('success', `Model pull started: ${pullModelName.value.trim()}`)
  } catch (e: unknown) {
    pullStatus.value = `Failed: ${errMsg(e)}`
    showToast('error', `Pull failed: ${errMsg(e)}`)
  } finally {
    pulling.value = false
  }
}

// ── 9. Reminders ──
const reminderForm = ref({ title: '', message: '', reminder_time: '', days_of_week: 'mon,tue,wed,thu,fri,sat,sun' })
const reminderSaving = ref(false)

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
    showToast('success', 'Reminder created')
  } catch (e: unknown) { showToast('error', `Create failed: ${errMsg(e)}`) }
  finally { reminderSaving.value = false }
}

async function testReminder(id: number) {
  try {
    await remindersStore.testNotification(id)
    showToast('success', 'Notification sent')
  } catch (e: unknown) { showToast('error', `Test failed: ${errMsg(e)}`) }
}

async function deleteReminder(id: number) {
  try {
    await remindersStore.remove(id)
    showToast('info', 'Reminder deleted')
  } catch (e: unknown) { showToast('error', errMsg(e)) }
}

// ── Helpers ──
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const dayLabels: Record<string, string> = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' }

// ── Auto Backup ──
const autoBackupEnabled = useLocalStorage<boolean>('diarium-auto-backup-enabled', false)
const autoBackupPath = useLocalStorage<string>('diarium-auto-backup-path', '~/Backups/diarilinux')
const autoBackupFrequency = useLocalStorage<string>('diarium-auto-backup-freq', '0 2 * * *')
const autoBackupRetention = useLocalStorage<number>('diarium-auto-backup-retention', 10)
const autoBackupStatus = ref<{ running: boolean; backup_scheduled: boolean; next_run: string | null } | null>(null)
const autoBackupSaving = ref(false)

async function toggleAutoBackup() {
  if (!autoBackupEnabled.value) {
    // Disabling — unschedule
    try {
      const { request } = await import('../../api/client')
      await request('/backup/schedule', { method: 'DELETE' })
      autoBackupStatus.value = { running: false, backup_scheduled: false, next_run: null }
    } catch { /* ignore */ }
  }
}

async function saveAutoBackup() {
  autoBackupSaving.value = true
  try {
    const { request } = await import('../../api/client')
    const expandedPath = autoBackupPath.value.replace(/^~/, '~')  // backend handles ~ expansion
    await request(`/backup/schedule?cron=${encodeURIComponent(autoBackupFrequency.value)}&backup_path=${encodeURIComponent(expandedPath)}&retention=${autoBackupRetention.value}`, { method: 'POST' })
    await loadAutoBackupStatus()
    autoBackupEnabled.value = true
  } catch (e: any) {
    alert(`Failed to save schedule: ${errMsg(e)}`)
  } finally {
    autoBackupSaving.value = false
  }
}

async function loadAutoBackupStatus() {
  try {
    const { request } = await import('../../api/client')
    autoBackupStatus.value = await request('/backup/schedule/status')
  } catch { /* ignore */ }
}

onMounted(() => {
  backup.fetchConfigs(); backup.fetchSnapshots(); syncStore.fetchStatus()
  pluginsStore.fetchAll(); templatesStore.fetchAll(); loadVoices()
  checkSystemDeps(); loadAppSettings(); loadOllamaModels()
  remindersStore.fetchAll(); loadAutoBackupStatus()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="px-3 py-2 border-b border-border">
      <h2 class="text-sm font-semibold text-text-primary">Settings</h2>
    </div>

    <!-- Tab sidebar + content panel -->
    <div class="flex flex-1 min-h-0">

      <!-- Vertical tab sidebar -->
      <nav class="w-[140px] shrink-0 border-r border-border py-1.5 px-1 space-y-0.5 overflow-y-auto">
        <button v-for="tab in tabs" :key="tab.id"
          @click="activeTab = tab.id"
          class="w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-[11px] font-medium cursor-pointer transition-colors"
          :class="activeTab === tab.id
            ? 'bg-accent/15 text-accent'
            : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'">
          <component :is="tab.icon" :size="13" />
          {{ tab.label }}
        </button>
      </nav>

      <!-- Content panel -->
      <div class="flex-1 overflow-y-auto px-3 py-2 space-y-2">

        <!-- ── General tab ── -->
        <template v-if="activeTab === 'general'">

          <!-- Appearance -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <Sun :size="11" /> Appearance
            </h3>
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
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <Sliders :size="11" /> Editor
            </h3>
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
                <div v-for="s in [
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
                ]" :key="s.keys" class="flex items-center justify-between px-2 py-1">
                  <span class="text-[11px] text-text-secondary">{{ s.desc }}</span>
                  <kbd class="px-1.5 py-0.5 bg-surface-hover rounded text-[9px] font-mono text-text-muted border border-border">{{ s.keys }}</kbd>
                </div>
              </div>
            </div>
          </section>

        </template>

        <!-- ── AI tab ── -->
        <template v-if="activeTab === 'ai'">

          <!-- AI Configuration -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <Brain :size="11" /> AI Configuration
            </h3>
            <div class="bg-surface rounded p-2 border border-border space-y-2">
              <div v-if="settingsLoading" class="text-[10px] text-text-muted">Loading...</div>
              <template v-else-if="appSettings">
                <!-- Model selector -->
                <div class="flex items-center gap-2">
                  <Sparkles :size="11" class="text-text-muted" />
                  <span class="text-[11px] text-text-secondary flex-1">Ollama model</span>
                  <select v-model="appSettings.ai.ollama_model"
                    class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]">
                    <option v-for="m in ollamaModels" :key="m.name" :value="m.name">{{ m.name }}</option>
                    <option :value="appSettings.ai.ollama_model">{{ appSettings.ai.ollama_model }} (current)</option>
                  </select>
                </div>
                <!-- Feature toggles -->
                <div class="space-y-1 border-t border-border pt-1.5">
                  <div class="text-[10px] text-text-muted uppercase tracking-wide mb-1">Features</div>
                  <label v-for="(label, key) in ({
                    enable_embeddings: 'Embeddings (semantic search)',
                    enable_tag_suggestions: 'Tag suggestions',
                    enable_sentiment: 'Sentiment analysis',
                    enable_summarization: 'Entry summarization',
                    enable_reflection_prompts: 'Reflection prompts',
                    enable_writer_block_helper: 'Writer\'s block helper',
                  } as Record<string, string>)" :key="key"
                    class="flex items-center gap-2 cursor-pointer">
                    <span class="text-[11px] text-text-secondary flex-1">{{ label }}</span>
                    <input type="checkbox" v-model="(appSettings.ai as any)[key]" class="accent-accent" />
                  </label>
                </div>
                <button @click="saveAISettings" :disabled="aiSaving"
                  class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
                  <Loader v-if="aiSaving" :size="10" class="animate-spin" />
                  Save AI Settings
                </button>
              </template>
              <!-- Pull model -->
              <div class="flex items-center gap-2 pt-1.5 border-t border-border">
                <DownloadIcon :size="11" class="text-text-muted shrink-0" />
                <span class="text-[11px] text-text-secondary flex-1">Pull model</span>
                <input v-model="pullModelName" placeholder="e.g. llama3.2:3b"
                  class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none w-32 hover:border-accent transition-colors" />
                <button @click="handlePullModel" :disabled="pulling || !pullModelName.trim()"
                  class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
                  <Loader v-if="pulling" :size="10" class="animate-spin" /> Pull
                </button>
              </div>
              <div v-if="pullStatus" class="text-[9px] text-text-muted">{{ pullStatus }}</div>
            </div>
          </section>

          <!-- AI Themes & Insights -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <Brain :size="11" /> Themes &amp; Insights
            </h3>
            <div class="bg-surface rounded p-2 border border-border space-y-2">
              <div class="flex items-center gap-2">
                <span class="text-[11px] text-text-secondary flex-1">Analyze journaling themes over</span>
                <select v-model.number="themesMonths"
                  class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors w-16">
                  <option v-for="m in [1,3,6,12,24]" :key="m" :value="m">{{ m }} month{{ m > 1 ? 's' : '' }}</option>
                </select>
                <button @click="fetchThemes" :disabled="themesLoading"
                  class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
                  <Loader v-if="themesLoading" :size="10" class="animate-spin" />
                  <Sparkles v-else :size="10" /> Analyze
                </button>
              </div>
              <div v-if="themes.length" class="space-y-1.5 max-h-60 overflow-y-auto">
                <div v-for="(t, i) in themes" :key="i" class="p-2 bg-surface-hover rounded space-y-1">
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-medium text-text-primary">{{ t.theme }}</span>
                    <span class="text-[10px] text-accent">{{ t.frequency }}</span>
                  </div>
                  <div v-if="t.months_mentioned.length" class="text-[10px] text-text-muted">
                    Months: {{ t.months_mentioned.join(', ') }}
                  </div>
                  <div v-if="t.insight" class="text-[11px] text-text-secondary">{{ t.insight }}</div>
                </div>
              </div>
              <div v-else-if="themesLoading" class="text-[10px] text-text-muted text-center py-2">Analyzing your journal...</div>
            </div>
          </section>

        </template>

        <!-- ── Data tab ── -->
        <template v-if="activeTab === 'data'">

          <!-- Storage -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <HardDrive :size="11" /> Storage
            </h3>
            <div class="bg-surface rounded p-2 border border-border space-y-1">
              <div v-if="appSettings?.storage" class="space-y-1">
                <div class="flex items-center justify-between text-[11px]">
                  <span class="text-text-secondary">Database</span>
                  <span class="text-text-primary">{{ formatBytes(appSettings.storage.db_size_bytes) }}</span>
                </div>
                <div class="flex items-center justify-between text-[11px]">
                  <span class="text-text-secondary">Entries</span>
                  <span class="text-text-primary">{{ appSettings.storage.entry_count }}</span>
                </div>
                <div class="flex items-center justify-between text-[11px]">
                  <span class="text-text-secondary">Media files</span>
                  <span class="text-text-primary">{{ appSettings.storage.media_count }} ({{ formatBytes(appSettings.storage.media_size_bytes) }})</span>
                </div>
                <div class="flex items-center justify-between text-[11px]">
                  <span class="text-text-secondary">Total</span>
                  <span class="text-text-primary font-medium">{{ formatBytes(appSettings.storage.db_size_bytes + appSettings.storage.media_size_bytes) }}</span>
                </div>
              </div>
              <div v-else class="text-[10px] text-text-muted">Loading...</div>
            </div>
          </section>

          <!-- Data (Import/Export) -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide mb-1">Data</h3>
            <div class="bg-surface rounded border border-border divide-y divide-border">
              <div class="p-2 flex items-center gap-2">
                <FileUp :size="12" class="text-text-muted shrink-0" />
                <span class="text-[11px] text-text-secondary flex-1">Import</span>
                <button class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50"
                  :disabled="fileImporting" @click="fileImportInput?.click()">
                  <Loader v-if="fileImporting" :size="10" class="animate-spin" />
                  <Upload v-else :size="10" /> {{ fileImporting ? 'Importing...' : 'Import file' }}
                </button>
                <input ref="fileImportInput" type="file" accept=".zip,.json,.diary" class="hidden" @change="handleFileImport" />
              </div>
              <div class="p-2 flex items-center gap-2">
                <Copy :size="12" class="text-text-muted shrink-0" />
                <span class="text-[11px] text-text-secondary flex-1">Remove duplicates</span>
                <button class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
                  :disabled="deduplicating" @click="handleDeduplicate">
                  <Loader v-if="deduplicating" :size="10" class="animate-spin" />
                  {{ deduplicating ? 'Scanning...' : 'Deduplicate' }}
                </button>
              </div>
              <div class="p-2 flex items-center gap-2 flex-wrap">
                <div class="flex items-center gap-1.5 flex-1 min-w-0">
                  <Download :size="12" class="text-text-muted shrink-0" />
                  <span class="text-[11px] text-text-secondary">Export</span>
                  <label class="flex items-center gap-0.5 text-[10px] cursor-pointer text-text-muted">
                    <input type="radio" v-model="exportRange" value="all" class="accent-accent" /> All
                  </label>
                  <label class="flex items-center gap-0.5 text-[10px] cursor-pointer text-text-muted">
                    <input type="radio" v-model="exportRange" value="range" class="accent-accent" /> Range
                  </label>
                  <template v-if="exportRange === 'range'">
                    <input v-model="exportFrom" type="date" class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary w-[90px]" />
                    <input v-model="exportTo" type="date" class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary w-[90px]" />
                  </template>
                </div>
                <div class="flex items-center gap-1">
                  <button class="px-1.5 py-0.5 rounded text-[10px] bg-accent text-white hover:bg-accent-hover cursor-pointer disabled:opacity-50"
                    :disabled="exportRange === 'range' && (!exportFrom || !exportTo)" @click="downloadMarkdown">.zip</button>
                  <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
                    :disabled="exportingHtml" @click="downloadHtmlExport">
                    <Loader v-if="exportingHtml" :size="9" class="animate-spin inline" />HTML</button>
                  <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer"
                    @click="downloadPdfExport">PDF</button>
                </div>
              </div>
              <div class="p-2 flex items-center gap-2">
                <Database :size="12" class="text-text-muted shrink-0" />
                <span class="text-[11px] text-text-secondary flex-1">Local archive</span>
                <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer"
                  @click="downloadExport"><Download :size="9" class="inline" /> Backup</button>
                <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
                  :disabled="importing" @click="importFileInput?.click()">
                  <Loader v-if="importing" :size="9" class="animate-spin inline" />Restore</button>
                <input ref="importFileInput" type="file" accept=".tar.gz,.tgz" class="hidden" @change="handleImport" />
              </div>
              <!-- Auto backup schedule -->
              <div class="p-2 space-y-1.5">
                <div class="flex items-center gap-2">
                  <input type="checkbox" v-model="autoBackupEnabled" class="accent-accent" @change="toggleAutoBackup" />
                  <span class="text-[11px] text-text-secondary flex-1">Auto backup (local)</span>
                  <span v-if="autoBackupStatus?.backup_scheduled" class="text-[9px] text-green-400">Scheduled</span>
                </div>
                <div v-if="autoBackupEnabled" class="space-y-1 pl-5">
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] text-text-muted w-12">Folder</span>
                    <input v-model="autoBackupPath"
                      placeholder="~/Backups/diarilinux"
                      class="flex-1 bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors" />
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] text-text-muted w-12">When</span>
                    <select v-model="autoBackupFrequency"
                      class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors">
                      <option value="0 2 * * *">Daily (2 AM)</option>
                      <option value="0 3 * * 0">Weekly (Sun 3 AM)</option>
                      <option value="0 3 1 * *">Monthly (1st, 3 AM)</option>
                    </select>
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] text-text-muted w-12">Keep</span>
                    <input v-model.number="autoBackupRetention" type="number" min="1" max="100"
                      class="w-12 bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors" />
                    <span class="text-[10px] text-text-muted">backups</span>
                  </div>
                  <button @click="saveAutoBackup" :disabled="autoBackupSaving"
                    class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
                    <Loader v-if="autoBackupSaving" :size="9" class="animate-spin" />
                    Save Schedule
                  </button>
                </div>
              </div>
            </div>
          </section>

          <!-- Cloud Backup -->
          <section>
            <div class="flex items-center justify-between mb-1">
              <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1">
                <Cloud :size="11" /> Cloud
              </h3>
              <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-accent text-white text-[10px] cursor-pointer hover:bg-accent-hover"
                @click="openCreateForm"><Plus :size="10" /> Add</button>
            </div>
            <div v-if="showCreate" class="bg-surface rounded p-2 mb-1 border border-accent/30 space-y-1">
              <div class="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 items-center">
                <span class="text-[10px] text-text-secondary">Provider</span>
                <select v-model="newProvider" class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary" @change="resetNewCredentials">
                  <option value="webdav">WebDAV</option>
                  <option value="google_drive">Google Drive</option>
                  <option value="onedrive">OneDrive</option>
                  <option value="dropbox">Dropbox</option>
                  <option value="nas">NAS</option>
                </select>
                <div v-if="newProvider === 'google_drive'" class="col-span-2 flex flex-col gap-1.5 py-1">
                  <button @click="startGoogleDriveAuth" class="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-accent text-white text-[11px] font-semibold cursor-pointer hover:bg-accent-hover transition-colors">
                    Sign in with Google
                  </button>
                  <div class="text-center">
                    <a href="#" @click.prevent="showManualGoogleFields = !showManualGoogleFields" class="text-[9px] text-text-muted hover:text-accent underline">
                      {{ showManualGoogleFields ? 'Hide manual settings' : 'Or configure manually (Advanced)' }}
                    </a>
                  </div>
                </div>
                <template v-if="newProvider !== 'google_drive' || showManualGoogleFields">
                  <template v-for="field in currentFields" :key="field.label">
                    <span class="text-[10px] text-text-secondary">{{ field.label }}</span>
                    <input v-model="newCredentials[field.label.toLowerCase().replace(/\s+/g, '_')]"
                      class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary" :placeholder="field.placeholder" />
                  </template>
                </template>
                <span class="text-[10px] text-text-secondary">Cron</span>
                <input v-model="newSchedule" class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary" placeholder="0 3 * * *" />
              </div>
              <div class="flex gap-1">
                <button class="px-2 py-0.5 rounded bg-accent text-white text-[10px] cursor-pointer hover:bg-accent-hover" @click="createConfig">Save</button>
                <button class="px-2 py-0.5 rounded text-[10px] text-text-secondary cursor-pointer" @click="showCreate = false">Cancel</button>
              </div>
            </div>
            <div v-for="config in backup.configs" :key="config.id" class="bg-surface rounded p-1.5 mb-0.5 border border-border">
              <div class="flex items-center gap-1.5 mb-1">
                <span class="text-[11px] font-medium text-text-primary capitalize">{{ config.provider.replace('_', ' ') }}</span>
                <span v-if="config.last_sync_at" class="text-[9px] text-text-muted">{{ new Date(config.last_sync_at).toLocaleDateString() }}</span>
                <button class="ml-auto p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-danger cursor-pointer" @click="deleteConfirm = config.id"><Trash2 :size="10" /></button>
              </div>
              <div class="flex items-center gap-1">
                <button class="px-1 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer" @click="testConn(config.id)">Test</button>
                <button class="flex items-center gap-0.5 px-1 py-0.5 rounded text-[10px] bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer disabled:opacity-50"
                  :disabled="backingUp === config.id" @click="runBackup(config.id)">
                  <Loader v-if="backingUp === config.id" :size="9" class="animate-spin" />{{ backingUp === config.id ? '...' : 'Backup' }}
                </button>
                <button class="flex items-center gap-0.5 px-1 py-0.5 rounded text-[10px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer disabled:opacity-50"
                  :disabled="restoring === config.id" @click="restoreConfirm = { configId: config.id, provider: config.provider }">
                  <RotateCcw v-if="restoring === config.id" :size="9" class="animate-spin" />{{ restoring === config.id ? '...' : 'Restore' }}
                </button>
              </div>
              <div v-if="testResult?.configId === config.id" class="mt-0.5 flex items-center gap-0.5 text-[10px]"
                :class="testResult.success ? 'text-green-400' : 'text-red-400'">
                <CheckCircle2 v-if="testResult.success" :size="10" /><AlertTriangle v-else :size="10" /> {{ testResult.message }}
              </div>
            </div>
            <div v-if="!backup.configs.length && !showCreate" class="text-[10px] text-text-muted py-1">No cloud backups configured.</div>
            <details v-if="backup.snapshots.length" class="mt-1">
              <summary class="text-[10px] text-text-muted cursor-pointer hover:text-text-primary">{{ backup.snapshots.length }} backups</summary>
              <div class="mt-0.5 space-y-0.5">
                <div v-for="snap in backup.snapshots.slice(0, 10)" :key="snap.id"
                  class="px-1.5 py-0.5 rounded text-[10px] flex items-center gap-1.5">
                  <CheckCircle2 v-if="snap.status === 'completed'" :size="9" class="text-green-400" />
                  <AlertTriangle v-else :size="9" class="text-red-400" />
                  <span class="text-text-muted">{{ snap.entries_synced }}e {{ snap.media_synced }}m</span>
                  <span class="ml-auto text-text-muted">{{ new Date(snap.started_at).toLocaleDateString() }}</span>
                </div>
              </div>
            </details>
          </section>

          <!-- Sync -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide mb-1">Sync</h3>
            <div class="bg-surface rounded p-2 border border-border">
              <div v-if="syncStore.status" class="flex items-center gap-3 text-[10px] mb-1.5">
                <span :class="syncStore.status.status === 'ok' ? 'text-green-400' : 'text-accent'">{{ syncStore.status.status }}</span>
                <span class="text-text-muted">{{ syncStore.status.pending_count }} pending</span>
                <span class="text-text-muted ml-auto">{{ syncStore.status.last_sync_at ? new Date(syncStore.status.last_sync_at).toLocaleDateString() : '—' }}</span>
              </div>
              <div class="flex items-center gap-1">
                <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer disabled:opacity-50"
                  :disabled="syncPushing" @click="handleSyncPush">
                  <Loader v-if="syncPushing" :size="9" class="animate-spin" /><ArrowUp v-else :size="9" /> Push
                </button>
                <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
                  :disabled="syncPulling" @click="handleSyncPull">
                  <Loader v-if="syncPulling" :size="9" class="animate-spin" /><ArrowDown v-else :size="9" /> Pull
                </button>
                <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer"
                  @click="handleSyncFlush"><RefreshCw :size="9" /> Flush</button>
              </div>
            </div>
          </section>

        </template>

        <!-- ── Features tab ── -->
        <template v-if="activeTab === 'features'">

          <!-- Read Aloud (TTS) -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <Volume2 :size="11" /> Read Aloud
            </h3>
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
                <div class="text-[9px] text-text-muted mt-0.5">Browse and install community plugins — coming soon.</div>
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
              <div v-else-if="depsStatus.all_installed" class="flex items-center gap-1 text-[10px] text-green-400">
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

        <!-- ── About tab ── -->
        <template v-if="activeTab === 'about'">

          <!-- About -->
          <section>
            <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
              <InfoIcon :size="11" /> About
            </h3>
            <div class="bg-surface rounded p-3 border border-border space-y-1.5 text-center">
              <div class="text-sm font-semibold text-text-primary">{{ appSettings?.app_name ?? 'Diarilinux' }}</div>
              <div class="text-[10px] text-text-muted">Version {{ appSettings?.version ?? '0.1.0' }}</div>
              <div class="text-[10px] text-text-secondary">Privacy-first, offline-first journaling for Linux</div>
              <div class="text-[10px] text-accent italic pt-1">Dedicated to my son Tariq Al Fayad</div>
              <div class="flex justify-center gap-3 pt-1">
                <a href="https://github.com/diarilinux/diarilinux" target="_blank" class="text-[10px] text-accent hover:underline">GitHub</a>
                <a href="https://github.com/diarilinux/diarilinux/issues" target="_blank" class="text-[10px] text-accent hover:underline">Report Issue</a>
                <a href="https://github.com/diarilinux/diarilinux/blob/main/LICENSE" target="_blank" class="text-[10px] text-accent hover:underline">License</a>
              </div>
            </div>
          </section>

          <!-- Danger Zone -->
          <section class="pb-2">
            <div class="bg-surface rounded p-2 border border-danger/30">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-[11px] font-medium text-danger">Reset Database</div>
                  <div class="text-[10px] text-text-secondary">Delete all entries, tags, and media.</div>
                </div>
                <button class="px-2 py-0.5 rounded text-[10px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer"
                  @click="showResetConfirm = true">Reset</button>
              </div>
              <div v-if="showResetConfirm" class="mt-2 p-2 bg-danger/10 rounded border border-danger/40 space-y-1.5">
                <p class="text-[11px] text-danger font-medium flex items-center gap-1">
                  <AlertTriangle :size="12" /> This cannot be undone.
                </p>
                <input v-model="resetConfirmText"
                  class="w-full px-2 py-1 bg-surface border border-danger/40 rounded text-[11px] text-text-primary placeholder-text-muted outline-none focus:border-danger"
                  placeholder='Type "RESET" to confirm' />
                <div class="flex items-center gap-2">
                  <button class="px-3 py-0.5 rounded text-[10px] font-medium bg-danger text-white hover:bg-red-600 cursor-pointer disabled:opacity-40"
                    :disabled="resetConfirmText !== 'RESET' || resetting" @click="handleReset">
                    <Loader v-if="resetting" :size="9" class="animate-spin inline" />
                    {{ resetting ? 'Erasing...' : 'Erase Everything' }}
                  </button>
                  <button class="px-2 py-0.5 rounded text-[10px] text-text-secondary cursor-pointer"
                    @click="showResetConfirm = false; resetConfirmText = ''">Cancel</button>
                </div>
              </div>
            </div>
          </section>

        </template>

      </div>
    </div>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast" class="absolute bottom-3 left-3 right-3 flex items-center gap-1.5 px-2 py-1 rounded border text-[11px]"
        :class="{
          'bg-green-900/80 border-green-700 text-green-200': toast.type === 'success',
          'bg-red-900/80 border-red-700 text-red-200': toast.type === 'error',
          'bg-surface border-border text-text-primary': toast.type === 'info',
        }">
        <CheckCircle2 v-if="toast.type === 'success'" :size="12" />
        <AlertTriangle v-else-if="toast.type === 'error'" :size="12" />
        <Info v-else :size="12" />
        {{ toast.message }}
        <button class="ml-auto p-0.5 cursor-pointer" @click="toast = null"><X :size="11" /></button>
      </div>
    </Transition>

    <ConfirmDialog v-if="restoreConfirm" title="Restore from backup?"
      :message="`Replace all local data with backup from ${restoreConfirm.provider.replace('_', ' ')}?`"
      @confirm="confirmRestore" @cancel="restoreConfirm = null" />
    <ConfirmDialog v-if="deleteConfirm" title="Delete config?" message="Snapshots kept."
      @confirm="confirmDelete" @cancel="deleteConfirm = null" />
  </div>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
