<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBackupStore } from '../../../stores/backup'
import { backupApi } from '../../../api/backup'
import { entriesApi } from '../../../api/entries'
import { exportHtml, getExportPdfUrl, exportDiarium } from '../../../api/export'
import { useEntriesStore } from '../../../stores/entries'
import { useSyncStore } from '../../../stores/sync'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { useLocalStorage } from '@vueuse/core'
import {
  Cloud, RefreshCw, RotateCcw, Plus, Trash2,
  Download, Upload, AlertTriangle, CheckCircle2,
  Loader, FileUp, Database, Copy, HardDrive
} from 'lucide-vue-next'
import ConfirmDialog from '../../common/ConfirmDialog.vue'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import SkeletonCard from '../shared/SkeletonCard.vue'

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
const exportingDiarium = ref(false)
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

async function downloadDiarium() {
  exportingDiarium.value = true
  try {
    const json = await exportDiarium(exportFrom.value || undefined, exportTo.value || undefined)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    Object.assign(document.createElement('a'), { href: url, download: 'diarium-export.json' }).click()
    URL.revokeObjectURL(url)
  } catch (e: unknown) { emit('toast', 'error', `Diarium export failed: ${errMsg(e)}`) }
  finally { exportingDiarium.value = false }
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
    setTimeout(async () => { await backup.fetchConfigs() }, 6000)
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
  set: (val: string) => { autoBackupFrequency.value = timeToCron(val, autoBackupFreqType.value) }
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
  set: (val: string) => { autoBackupFrequency.value = timeToCron(autoBackupTime.value, val) }
})

function timeToCron(time: string, freq: string): string {
  const [h, m] = time.split(':').map(Number)
  const hh = isNaN(h) ? 2 : h; const mm = isNaN(m) ? 0 : m
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
    await request(`/backup/schedule?cron=${encodeURIComponent(autoBackupFrequency.value)}&backup_path=${encodeURIComponent(autoBackupPath.value)}&retention=${autoBackupRetention.value}`, { method: 'POST' })
    await loadAutoBackupStatus()
    autoBackupEnabled.value = true
  } catch (e: any) {
    emit('toast', 'error', `Failed to save schedule: ${errMsg(e)}`)
  } finally { autoBackupSaving.value = false }
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
  <SettingsSection title="Storage" :icon="HardDrive" description="Disk usage and entry statistics" card-class="p-3">
    <div v-if="appSettings?.storage" class="grid grid-cols-2 gap-x-6 gap-y-1.5">
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Database</span>
        <span class="text-text-primary font-medium">{{ formatBytes(appSettings.storage.db_size_bytes) }}</span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Entries</span>
        <span class="text-text-primary font-medium">{{ appSettings.storage.entry_count }}</span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Media files</span>
        <span class="text-text-primary font-medium">{{ appSettings.storage.media_count }} ({{ formatBytes(appSettings.storage.media_size_bytes) }})</span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Total</span>
        <span class="text-text-primary font-semibold">{{ formatBytes(appSettings.storage.db_size_bytes + appSettings.storage.media_size_bytes) }}</span>
      </div>
    </div>
    <SkeletonCard v-else :lines="4" />
  </SettingsSection>

  <!-- Import / Export -->
  <SettingsSection title="Import / Export" :icon="FileUp" description="Bring entries in or export your journal"
    card-class="divide-y divide-border">
    <!-- Import -->
    <div class="p-3">
      <SettingRow :icon="Upload" label="Import entries">
        <button class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50"
          :disabled="fileImporting" @click="fileImportInput?.click()">
          <Loader v-if="fileImporting" :size="11" class="animate-spin" />
          {{ fileImporting ? 'Importing...' : 'Import file' }}
        </button>
        <input ref="fileImportInput" type="file" accept=".zip,.json,.diary" class="hidden" @change="handleFileImport" />
      </SettingRow>
    </div>
    <!-- Deduplicate -->
    <div class="p-3">
      <SettingRow :icon="Copy" label="Remove duplicates">
        <button class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
          :disabled="deduplicating" @click="handleDeduplicate">
          <Loader v-if="deduplicating" :size="11" class="animate-spin" />
          {{ deduplicating ? 'Scanning...' : 'Deduplicate' }}
        </button>
      </SettingRow>
    </div>
    <!-- Export -->
    <div class="p-3 space-y-2">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Download :size="12" class="text-text-muted shrink-0" />
        <span class="text-[12px] text-text-secondary">Export</span>
        <label class="flex items-center gap-1 text-[11px] cursor-pointer text-text-muted">
          <input type="radio" v-model="exportRange" value="all" class="accent-accent" /> All
        </label>
        <label class="flex items-center gap-1 text-[11px] cursor-pointer text-text-muted">
          <input type="radio" v-model="exportRange" value="range" class="accent-accent" /> Range
        </label>
        <template v-if="exportRange === 'range'">
          <input v-model="exportFrom" type="date" class="settings-input w-28" />
          <input v-model="exportTo" type="date" class="settings-input w-28" />
        </template>
      </div>
      <div class="flex items-center gap-1.5 pl-[26px]">
        <button class="px-2 py-0.5 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer disabled:opacity-50"
          :disabled="exportRange === 'range' && (!exportFrom || !exportTo)" @click="downloadMarkdown">ZIP</button>
        <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
          :disabled="exportRange === 'range' && (!exportFrom || !exportTo) || exportingDiarium" @click="downloadDiarium">
          <Loader v-if="exportingDiarium" :size="10" class="animate-spin inline" /> Diarium</button>
        <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50"
          :disabled="exportingHtml" @click="downloadHtmlExport">
          <Loader v-if="exportingHtml" :size="10" class="animate-spin inline" /> HTML</button>
        <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer"
          @click="downloadPdfExport">PDF</button>
      </div>
    </div>
  </SettingsSection>

  <!-- Backup -->
  <SettingsSection title="Backup" :icon="Database" description="Local archive and scheduled backups"
    card-class="divide-y divide-border">
    <!-- Local archive -->
    <div class="p-3">
      <SettingRow :icon="HardDrive" label="Local archive">
        <div class="flex items-center gap-1.5">
          <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors"
            @click="downloadExport"><Download :size="10" class="inline" /> Backup</button>
          <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer disabled:opacity-50 transition-colors"
            :disabled="importing" @click="importFileInput?.click()">
            <Loader v-if="importing" :size="10" class="animate-spin inline" /> Restore</button>
        </div>
        <input ref="importFileInput" type="file" accept=".tar.gz,.tgz" class="hidden" @change="handleImport" />
      </SettingRow>
    </div>
    <!-- Auto backup schedule -->
    <div class="p-3 space-y-2">
      <div class="flex items-center gap-2.5">
        <input type="checkbox" v-model="autoBackupEnabled" class="accent-accent" @change="toggleAutoBackup" />
        <span class="text-[12px] text-text-secondary flex-1">Auto backup (local)</span>
        <span v-if="autoBackupStatus?.backup_scheduled" class="text-[10px] text-green-400 font-medium">Scheduled</span>
      </div>
      <div v-if="autoBackupEnabled" class="space-y-1.5 pl-6">
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-text-muted w-14">Folder</span>
          <input v-model="autoBackupPath" placeholder="~/Backups/dailybyte"
            class="settings-input flex-1" />
        </div>
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-text-muted w-14">Time</span>
          <input v-model="autoBackupTime" type="time" class="settings-input" />
        </div>
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-text-muted w-14">Freq</span>
          <select v-model="autoBackupFreqType" class="settings-select">
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
        <p class="text-[10px] text-accent/70 pl-16">{{ autoBackupHumanPreview }}</p>
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-text-muted w-14">Keep</span>
          <input v-model.number="autoBackupRetention" type="number" min="1" max="100"
            class="settings-input w-14" />
          <span class="text-[11px] text-text-muted">backups</span>
        </div>
        <button @click="saveAutoBackup" :disabled="autoBackupSaving"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover cursor-pointer transition-colors disabled:opacity-50">
          <Loader v-if="autoBackupSaving" :size="10" class="animate-spin" />
          Save Schedule
        </button>
      </div>
    </div>
  </SettingsSection>

  <!-- Cloud -->
  <SettingsSection title="Cloud" :icon="Cloud" description="Sync your journal to cloud storage">
    <template #actions>
      <button class="flex items-center gap-1 px-2.5 py-0.5 rounded-md bg-accent text-white text-[11px] font-medium cursor-pointer hover:bg-accent-hover transition-colors"
        @click="openCreateForm"><Plus :size="11" /> Add</button>
    </template>

    <!-- Create form -->
    <div v-if="showCreate" class="mb-3 p-3 border border-accent/30 rounded-md space-y-2">
      <div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 items-center">
        <span class="text-[11px] text-text-secondary">Provider</span>
        <select v-model="newProvider" class="settings-select" @change="resetNewCredentials">
          <option value="webdav">WebDAV</option>
          <option value="google_drive">Google Drive</option>
          <option value="mega">MEGA</option>
          <option value="onedrive">OneDrive</option>
          <option value="dropbox">Dropbox</option>
          <option value="nas">NAS</option>
        </select>
        <div v-if="newProvider === 'google_drive'" class="col-span-2 flex flex-col gap-1.5 py-1">
          <button @click="startGoogleDriveAuth" class="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-accent text-white text-[11px] font-semibold cursor-pointer hover:bg-accent-hover transition-colors">
            Sign in with Google
          </button>
          <div class="text-center">
            <a href="#" @click.prevent="showManualGoogleFields = !showManualGoogleFields" class="text-[10px] text-text-muted hover:text-accent underline">
              {{ showManualGoogleFields ? 'Hide manual settings' : 'Or configure manually (Advanced)' }}
            </a>
          </div>
        </div>
        <template v-if="newProvider !== 'google_drive' || showManualGoogleFields">
          <template v-for="field in currentFields" :key="field.label">
            <span class="text-[11px] text-text-secondary">{{ field.label }}</span>
            <input v-model="newCredentials[field.label.toLowerCase().replace(/\s+/g, '_')]"
              class="settings-input" :placeholder="field.placeholder" />
          </template>
        </template>
        <span class="text-[11px] text-text-secondary">Cron</span>
        <input v-model="newSchedule" class="settings-input" placeholder="0 3 * * *" />
      </div>
      <div class="flex gap-1.5">
        <button class="px-3 py-0.5 rounded-md bg-accent text-white text-[11px] font-medium cursor-pointer hover:bg-accent-hover transition-colors" @click="createConfig">Save</button>
        <button class="px-3 py-0.5 rounded-md text-[11px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors" @click="showCreate = false">Cancel</button>
      </div>
    </div>

    <!-- Configs -->
    <div v-for="config in backup.configs" :key="config.id" class="p-2.5 mb-1 last:mb-0 rounded-md border border-border">
      <div class="flex items-center gap-2 mb-1.5">
        <span class="text-[12px] font-medium text-text-primary capitalize">{{ config.provider.replace('_', ' ') }}</span>
        <span v-if="config.last_sync_at" class="text-[10px] text-text-muted">{{ new Date(config.last_sync_at).toLocaleDateString() }}</span>
        <button class="ml-auto p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-danger cursor-pointer transition-colors" @click="deleteConfirm = config.id"><Trash2 :size="11" /></button>
      </div>
      <div class="flex items-center gap-1.5">
        <button class="px-2 py-0.5 rounded-md text-[11px] bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors" @click="testConn(config.id)">Test</button>
        <button class="flex items-center gap-0.5 px-2 py-0.5 rounded-md text-[11px] bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer transition-colors disabled:opacity-50"
          :disabled="backingUp === config.id" @click="runBackup(config.id)">
          <Loader v-if="backingUp === config.id" :size="10" class="animate-spin" />{{ backingUp === config.id ? '...' : 'Backup' }}
        </button>
        <button class="flex items-center gap-0.5 px-2 py-0.5 rounded-md text-[11px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer transition-colors disabled:opacity-50"
          :disabled="restoring === config.id" @click="restoreConfirm = { configId: config.id, provider: config.provider }">
          <RotateCcw v-if="restoring === config.id" :size="10" class="animate-spin" />{{ restoring === config.id ? '...' : 'Restore' }}
        </button>
      </div>
      <div v-if="testResult?.configId === config.id" class="mt-1 flex items-center gap-1 text-[11px]"
        :class="testResult.success ? 'text-green-400' : 'text-red-400'">
        <CheckCircle2 v-if="testResult.success" :size="11" /><AlertTriangle v-else :size="11" /> {{ testResult.message }}
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!backup.configs.length && !showCreate" class="text-center py-4">
      <Cloud :size="20" class="mx-auto text-text-muted mb-1.5" />
      <p class="text-[11px] text-text-secondary">No cloud backups configured.</p>
      <p class="text-[10px] text-text-muted mt-0.5">Click Add to connect a cloud provider.</p>
    </div>

    <!-- Snapshots -->
    <details v-if="backup.snapshots.length" class="mt-2 border-t border-border pt-2">
      <summary class="text-[11px] text-text-muted cursor-pointer hover:text-text-primary transition-colors">{{ backup.snapshots.length }} backups</summary>
      <div class="mt-1 space-y-0.5">
        <div v-for="snap in backup.snapshots.slice(0, 10)" :key="snap.id"
          class="px-2 py-0.5 rounded text-[11px] flex items-center gap-2">
          <CheckCircle2 v-if="snap.status === 'completed'" :size="10" class="text-green-400" />
          <AlertTriangle v-else :size="10" class="text-red-400" />
          <span class="text-text-muted">{{ snap.entries_synced }}e {{ snap.media_synced }}m</span>
          <span class="ml-auto text-text-muted">{{ new Date(snap.started_at).toLocaleDateString() }}</span>
        </div>
      </div>
    </details>
  </SettingsSection>

  <!-- Sync -->
  <SettingsSection title="Sync" :icon="RefreshCw" description="Manage data synchronization queue">
    <div v-if="syncStore.status" class="flex items-center gap-3 text-[11px] mb-2">
      <span :class="syncStore.status.status === 'ok' ? 'text-green-400' : 'text-accent'" class="font-medium">{{ syncStore.status.status }}</span>
      <span class="text-text-muted">{{ syncStore.status.pending_count }} pending</span>
      <span class="text-text-muted ml-auto">{{ syncStore.status.last_sync_at ? new Date(syncStore.status.last_sync_at).toLocaleDateString() : '—' }}</span>
    </div>
    <div class="flex items-center gap-1.5">
      <button class="flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-accent/15 text-accent hover:bg-accent/25 cursor-pointer transition-colors disabled:opacity-50"
        :disabled="syncPushing" @click="handleSyncPush">
        <Loader v-if="syncPushing" :size="10" class="animate-spin" />Push
      </button>
      <button class="flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors disabled:opacity-50"
        :disabled="syncPulling" @click="handleSyncPull">
        <Loader v-if="syncPulling" :size="10" class="animate-spin" />Pull
      </button>
      <button class="flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer transition-colors"
        @click="handleSyncFlush"><RefreshCw :size="10" /> Flush</button>
    </div>
  </SettingsSection>

  <ConfirmDialog v-if="restoreConfirm" title="Restore from backup?"
    :message="`Replace all local data with backup from ${restoreConfirm.provider.replace('_', ' ')}?`"
    @confirm="confirmRestore" @cancel="restoreConfirm = null" />
  <ConfirmDialog v-if="deleteConfirm" title="Delete config?" message="Snapshots kept."
    @confirm="confirmDelete" @cancel="deleteConfirm = null" />
</template>
