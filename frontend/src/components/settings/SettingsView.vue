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
import {
  Cloud, RefreshCw, RotateCcw, Plus, Trash2,
  Download, Upload, AlertTriangle, CheckCircle2, X, Info,
  ArrowUp, ArrowDown, Puzzle, Power, PowerOff, Loader, FileUp, MapPin, Database, Copy, Volume2, LayoutTemplate,
  Wrench, MonitorCheck, Sparkles, Brain, Download as DownloadIcon
} from 'lucide-vue-next'
import ConfirmDialog from '../common/ConfirmDialog.vue'
import { useTemplatesStore } from '../../stores/templates'

const backup = useBackupStore()
const syncStore = useSyncStore()
const entriesStore = useEntriesStore()
const pluginsStore = usePluginsStore()
const templatesStore = useTemplatesStore()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

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

function openCreateForm() {
  newProvider.value = 'webdav'; resetNewCredentials(); newSchedule.value = ''; showCreate.value = true
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
    const res = await fetch('/api/v1/tts/voices')
    ttsVoices.value = await res.json()
  } catch { /* ignore */ }
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

onMounted(() => { backup.fetchConfigs(); backup.fetchSnapshots(); syncStore.fetchStatus(); pluginsStore.fetchAll(); templatesStore.fetchAll(); loadVoices(); checkSystemDeps() })
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="px-3 py-2 border-b border-border">
      <h2 class="text-sm font-semibold text-text-primary">Settings</h2>
    </div>

    <div class="flex-1 overflow-y-auto px-3 py-2 space-y-2">

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
            <Volume2 :size="11" class="text-text-muted" />
            <span class="text-[11px] text-text-secondary flex-1">Read Aloud voice</span>
            <select
              v-model="ttsVoice"
              class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]"
              :disabled="ttsVoicesLoading"
            >
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
            <LayoutTemplate :size="11" class="text-text-muted" />
            <span class="text-[11px] text-text-secondary flex-1">Default template</span>
            <select
              v-model.number="defaultTemplateId"
              class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors max-w-[180px]"
            >
              <option :value="null">None</option>
              <option v-for="t in templatesStore.templates" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
        </div>
      </section>

      <!-- System Setup (Tauri desktop only) -->
      <section v-if="isTauri">
        <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
          <Wrench :size="11" /> System Setup
        </h3>
        <div class="bg-surface rounded p-2 border border-border space-y-1.5">
          <!-- Deps status -->
          <div v-if="depsStatus === null" class="text-[10px] text-text-muted">Checking dependencies...</div>
          <div v-else-if="depsStatus.all_installed" class="flex items-center gap-1 text-[10px] text-green-400">
            <MonitorCheck :size="11" /> All system dependencies installed
          </div>
          <div v-else class="space-y-1">
            <div class="flex items-center gap-1 text-[10px]"
              :class="depsStatus.tesseract ? 'text-green-400' : 'text-red-400'">
              <CheckCircle2 v-if="depsStatus.tesseract" :size="10" />
              <AlertTriangle v-else :size="10" />
              Tesseract OCR {{ depsStatus.tesseract ? '(installed)' : '(missing — needed for image text extraction)' }}
            </div>
            <div class="flex items-center gap-1 text-[10px]"
              :class="depsStatus.ollama ? 'text-green-400' : 'text-red-400'">
              <CheckCircle2 v-if="depsStatus.ollama" :size="10" />
              <AlertTriangle v-else :size="10" />
              Ollama AI {{ depsStatus.ollama ? '(installed)' : '(missing — needed for grammar check & AI features)' }}
            </div>
            <button
              class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50 mt-1"
              :disabled="setupRunning" @click="runSystemSetup">
              <Loader v-if="setupRunning" :size="10" class="animate-spin" />
              <Wrench v-else :size="10" />
              {{ setupRunning ? 'Installing...' : 'Install Missing Dependencies' }}
            </button>
            <p class="text-[9px] text-text-muted">Installs Tesseract OCR, Ollama AI (with llama3.2 model), and PDF export libraries.</p>
          </div>
          <!-- Setup output -->
          <div v-if="setupOutput" class="mt-1 p-1.5 rounded bg-black/30 text-[9px] font-mono text-green-300 max-h-32 overflow-y-auto whitespace-pre-wrap">
            {{ setupOutput }}
          </div>
          <!-- Pull AI Model -->
          <div class="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-border">
            <DownloadIcon :size="11" class="text-text-muted shrink-0" />
            <span class="text-[11px] text-text-secondary flex-1">Pull AI model</span>
            <input v-model="pullModelName" placeholder="e.g. llama3.2:3b"
              class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none w-32 hover:border-accent transition-colors" />
            <button @click="handlePullModel" :disabled="pulling || !pullModelName.trim()"
              class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
              <Loader v-if="pulling" :size="10" class="animate-spin" />
              Pull
            </button>
          </div>
          <div v-if="pullStatus" class="text-[9px] text-text-muted mt-0.5">{{ pullStatus }}</div>
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
              <Sparkles v-else :size="10" />
              Analyze
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

      <!-- Import / Export -->
      <section>
        <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide mb-1">Data</h3>
        <div class="bg-surface rounded border border-border divide-y divide-border">
          <!-- Import -->
          <div class="p-2 flex items-center gap-2">
            <FileUp :size="12" class="text-text-muted shrink-0" />
            <span class="text-[11px] text-text-secondary flex-1">Import</span>
            <button class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50"
              :disabled="fileImporting" @click="fileImportInput?.click()">
              <Loader v-if="fileImporting" :size="10" class="animate-spin" />
              <Upload v-else :size="10" />
              {{ fileImporting ? 'Importing...' : 'Import file' }}
            </button>
            <input ref="fileImportInput" type="file" accept=".zip,.json,.diary" class="hidden" @change="handleFileImport" />
          </div>
          <!-- Deduplicate -->
          <div class="p-2 flex items-center gap-2">
            <Copy :size="12" class="text-text-muted shrink-0" />
            <span class="text-[11px] text-text-secondary flex-1">Remove duplicates</span>
            <button class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
              :disabled="deduplicating" @click="handleDeduplicate">
              <Loader v-if="deduplicating" :size="10" class="animate-spin" />
              {{ deduplicating ? 'Scanning...' : 'Deduplicate' }}
            </button>
          </div>
          <!-- Export buttons -->
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
          <!-- Local archive -->
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
            <template v-for="field in currentFields" :key="field.label">
              <span class="text-[10px] text-text-secondary">{{ field.label }}</span>
              <input v-model="newCredentials[field.label.toLowerCase().replace(/\s+/g, '_')]"
                class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary" :placeholder="field.placeholder" />
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

        <!-- Snapshot history (collapsible) -->
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

      <!-- Plugins -->
      <section>
        <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
          <Puzzle :size="11" /> Plugins
        </h3>
        <div class="bg-surface rounded p-2 border border-border space-y-1">
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
          class="bg-surface rounded px-2 py-1 mt-0.5 border border-border flex items-center gap-2">
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
        <div v-if="!pluginsStore.plugins.length" class="text-[10px] text-text-muted mt-1">No plugins.</div>
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
