<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBackupStore } from '../../../stores/backup'
import { backupApi } from '../../../api/backup'
import { entriesApi } from '../../../api/entries'
import { exportHtml, getExportPdfUrl } from '../../../api/export'
import { useEntriesStore } from '../../../stores/entries'
import { useSyncStore } from '../../../stores/sync'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { useLocalStorage } from '@vueuse/core'
import {
  Cloud, RefreshCw, RotateCcw, Plus, Trash2,
  Download, Upload, AlertTriangle, CheckCircle2,
  Loader, FileUp, Database, Copy
} from 'lucide-vue-next'
import ConfirmDialog from '../../common/ConfirmDialog.vue'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const backup = useBackupStore()
const entriesStore = useEntriesStore()
const syncStore = useSyncStore()

// ── Storage ──
const appSettings = ref<AppSettings | null>(null)
async function loadAppSettings() {
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
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
    emit('toast', 'success', `Imported ${r.imported} entries`)
  } catch (e: unknown) { emit('toast', 'error', `Import failed: ${errMsg(e)}`) }
  finally { fileImporting.value = false; if (fileImportInput.value) fileImportInput.value.value = '' }
}

async function handleImport(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  importing.value = true
  try { const r = await backupApi.importLocal(file); entriesStore.refreshAll(); emit('toast', 'success', `Restored — ${r.restored.join(', ')}`) }
  catch (e: unknown) { emit('toast', 'error', `Import failed: ${errMsg(e)}`) }
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
  } catch (e: unknown) { emit('toast', 'error', `HTML export failed: ${errMsg(e)}`) }
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
      emit('toast', 'info', 'No duplicates found')
    } else {
      emit('toast', 'success', `Removed ${r.duplicates_removed} duplicate${r.duplicates_removed > 1 ? 's' : ''} across ${r.groups_found} group${r.groups_found > 1 ? 's' : ''}`)
    }
  } catch (e: unknown) { emit('toast', 'error', `Deduplicate failed: ${errMsg(e)}`) }
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
  mega: [
    { label: 'Email', placeholder: 'user@example.com' },
    { label: 'Password', placeholder: 'MEGA account password' },
  ],
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
    emit('toast', 'info', 'Opening Google Authentication in browser...')
    showCreate.value = false
    setTimeout(async () => {
      await backup.fetchConfigs()
    }, 6000)
  } catch (e: unknown) {
    emit('toast', 'error', `Google auth initiation failed: ${errMsg(e)}`)
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
    emit('toast', snap.status === 'completed' ? 'success' : 'error',
      snap.status === 'completed' ? `Backup done — ${snap.entries_synced}e ${snap.media_synced}m` : `Backup failed: ${snap.error_message ?? 'unknown'}`)
  } catch (e: unknown) { emit('toast', 'error', `Backup failed: ${errMsg(e)}`) }
  finally { backingUp.value = null }
}

async function confirmRestore() {
  if (!restoreConfirm.value) return
  const { configId, provider } = restoreConfirm.value; restoreConfirm.value = null; restoring.value = configId
  try {
    const r = await backup.restore(configId)
    emit('toast', 'success', `Restored from ${provider.replace('_', ' ')} — ${(r as any).entries_restored ?? 0}e ${(r as any).media_restored ?? 0}m`)
  } catch (e: unknown) { emit('toast', 'error', `Restore failed: ${errMsg(e)}`) }
  finally { restoring.value = null }
}

async function confirmDelete() {
  if (!deleteConfirm.value) return
  try { await backup.deleteConfig(deleteConfirm.value); emit('toast', 'info', 'Config deleted') }
  catch (e: unknown) { emit('toast', 'error', `Delete failed: ${errMsg(e)}`) }
  finally { deleteConfirm.value = null }
}

// ── Sync ──
const syncPushing = ref(false)
const syncPulling = ref(false)

async function handleSyncPush() {
  syncPushing.value = true
  try { await syncStore.push('local_file'); emit('toast', 'success', 'Push done') }
  catch (e: unknown) { emit('toast', 'error', `Push failed: ${errMsg(e)}`) }
  finally { syncPushing.value = false }
}
async function handleSyncPull() {
  syncPulling.value = true
  try { await syncStore.pull('local_file'); emit('toast', 'success', 'Pull done') }
  catch (e: unknown) { emit('toast', 'error', `Pull failed: ${errMsg(e)}`) }
  finally { syncPulling.value = false }
}
async function handleSyncFlush() {
  try { await syncStore.flush(); emit('toast', 'success', 'Queue flushed'); syncStore.fetchStatus() }
  catch (e: unknown) { emit('toast', 'error', `Flush failed: ${errMsg(e)}`) }
}

// ── Auto Backup ──
const autoBackupEnabled = useLocalStorage<boolean>('diarium-auto-backup-enabled', false)
const autoBackupPath = useLocalStorage<string>('diarium-auto-backup-path', '~/Backups/dailybyte')
const autoBackupFrequency = useLocalStorage<string>('diarium-auto-backup-freq', '0 2 * * *')
const autoBackupRetention = useLocalStorage<number>('diarium-auto-backup-retention', 10)

const autoBackupTime = computed({
  get: () => {
    const parts = autoBackupFrequency.value.split(' ')
    if (parts.length >= 2) {
      const h = parts[1].padStart(2, '0')
      const m = parts[0].padStart(2, '0')
      return `${h}:${m}`
    }
    return '02:00'
  },
  set: (val: string) => {
    autoBackupFrequency.value = timeToCron(val, autoBackupFreqType.value)
  }
})
const autoBackupFreqType = computed({
  get: (): string => {
    const p = autoBackupFrequency.value.split(' ')
    if (p.length >= 5) {
      if (p[4] !== '*') return 'weekly'
      if (p[2] !== '*') return 'monthly'
    }
    return 'daily'
  },
  set: (val: string) => {
    autoBackupFrequency.value = timeToCron(autoBackupTime.value, val)
  }
})

function timeToCron(time: string, freq: string): string {
  const [h, m] = time.split(':').map(Number)
  const hh = isNaN(h) ? 2 : h
  const mm = isNaN(m) ? 0 : m
  if (freq === 'weekly') return `${mm} ${hh} * * 0`
  if (freq === 'monthly') return `${mm} ${hh} 1 * *`
  return `${mm} ${hh} * * *`
}

const autoBackupHumanPreview = computed(() => {
  const time = autoBackupTime.value
  const [h, m] = time.split(':').map(Number)
  const ampm = h >= 12 ? 'PM' : 'AM'
  const displayH = h === 0 ? 12 : h > 12 ? h - 12 : h
  const timeStr = `${displayH}:${String(m).padStart(2, '0')} ${ampm}`
  const freq = autoBackupFreqType.value
  if (freq === 'weekly') return `Runs weekly on Sunday at ${timeStr}`
  if (freq === 'monthly') return `Runs monthly on the 1st at ${timeStr}`
  return `Runs daily at ${timeStr}`
})
const autoBackupStatus = ref<{ running: boolean; backup_scheduled: boolean; next_run: string | null } | null>(null)
const autoBackupSaving = ref(false)

async function toggleAutoBackup() {
  if (!autoBackupEnabled.value) {
    try {
      const { request } = await import('../../../api/client')
      await request('/backup/schedule', { method: 'DELETE' })
      autoBackupStatus.value = { running: false, backup_scheduled: false, next_run: null }
    } catch { /* ignore */ }
  }
}

async function saveAutoBackup() {
  autoBackupSaving.value = true
  try {
    const { request } = await import('../../../api/client')
    const expandedPath = autoBackupPath.value
    await request(`/backup/schedule?cron=${encodeURIComponent(autoBackupFrequency.value)}&backup_path=${encodeURIComponent(expandedPath)}&retention=${autoBackupRetention.value}`, { method: 'POST' })
    await loadAutoBackupStatus()
    autoBackupEnabled.value = true
  } catch (e: any) {
    emit('toast', 'error', `Failed to save schedule: ${errMsg(e)}`)
  } finally {
    autoBackupSaving.value = false
  }
}

async function loadAutoBackupStatus() {
  try {
    const { request } = await import('../../../api/client')
    autoBackupStatus.value = await request('/backup/schedule/status')
  } catch { /* ignore */ }
}

onMounted(() => {
  backup.fetchConfigs(); backup.fetchSnapshots(); syncStore.fetchStatus()
  loadAppSettings(); loadAutoBackupStatus()
})
</script>

<template>
  <!-- Storage -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <Database :size="11" /> Storage
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
              placeholder="~/Backups/dailybyte"
              class="flex-1 bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors" />
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-text-muted w-12">Time</span>
            <input
              v-model="autoBackupTime"
              type="time"
              class="bg-surface border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors"
            />
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-text-muted w-12">Freq</span>
            <select v-model="autoBackupFreqType"
              class="bg-surface border border-border rounded px-1 py-0.5 text-[10px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors">
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
          <div class="text-[9px] text-accent/70 pl-14">{{ autoBackupHumanPreview }}</div>
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
          <option value="mega">MEGA</option>
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
          <Loader v-if="syncPushing" :size="9" class="animate-spin" />Push
        </button>
        <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
          :disabled="syncPulling" @click="handleSyncPull">
          <Loader v-if="syncPulling" :size="9" class="animate-spin" />Pull
        </button>
        <button class="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer"
          @click="handleSyncFlush"><RefreshCw :size="9" /> Flush</button>
      </div>
    </div>
  </section>

  <ConfirmDialog v-if="restoreConfirm" title="Restore from backup?"
    :message="`Replace all local data with backup from ${restoreConfirm.provider.replace('_', ' ')}?`"
    @confirm="confirmRestore" @cancel="restoreConfirm = null" />
  <ConfirmDialog v-if="deleteConfirm" title="Delete config?" message="Snapshots kept."
    @confirm="confirmDelete" @cancel="deleteConfirm = null" />
</template>
