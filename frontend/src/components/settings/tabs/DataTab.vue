<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { entriesApi } from '../../../api/entries'
import { exportHtml, getExportPdfUrl, exportDiarium, getExportDiariumDbUrl } from '../../../api/export'
import { useEntriesStore } from '../../../stores/entries'
import { getSettings, vacuumDatabase, checkIntegrity } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { saveFile, pickFile } from '../../../utils/fileDialog'
import {
  Download, Upload, Loader, FileUp,
  Database, Copy, HardDrive, Wrench, Shield, ChevronDown,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import SkeletonCard from '../shared/SkeletonCard.vue'
import SButton from '../shared/SButton.vue'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const entriesStore = useEntriesStore()

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

// ── Import ──
const importingZip = ref(false)
const importingHtml = ref(false)
const importingDiarium = ref(false)

async function runImport(file: File, flag: Ref<boolean>) {
  flag.value = true
  try {
    const r = await entriesApi.importFile(file)
    entriesStore.refreshAll()
    await loadAppSettings() // refresh counts after import
    emit('toast', 'success', `Imported ${r.imported} entries${r.skipped ? ` (${r.skipped} skipped)` : ''}`)
  } catch (e: unknown) { emit('toast', 'error', `Import failed: ${errMsg(e)}`) }
  finally { flag.value = false }
}

async function handleImportZip() {
  const file = await pickFile({ accept: '.zip,.json' })
  if (file) await runImport(file, importingZip)
}
async function handleImportHtml() {
  const file = await pickFile({ accept: '.html,.htm' })
  if (file) await runImport(file, importingHtml)
}
async function handleImportDiarium() {
  const file = await pickFile({ accept: '.json,.diary' })
  if (file) await runImport(file, importingDiarium)
}

// ── Export ──
const exportRange = ref<'all' | 'range'>('all')
const exportFrom = ref('')
const exportTo = ref('')
const exportMenuOpen = ref(false)
const exportingHtml = ref(false)
const exportingDiarium = ref(false)
const exportingDiariumDb = ref(false)

const rangeError = computed(() => {
  if (exportRange.value !== 'range') return ''
  if (!exportFrom.value || !exportTo.value) return ''
  return exportFrom.value > exportTo.value ? 'Start date must be before end date' : ''
})
const exportDisabled = computed(() => !!rangeError.value || (exportRange.value === 'range' && (!exportFrom.value || !exportTo.value)))
const rangeStart = computed(() => exportRange.value === 'range' ? (exportFrom.value || undefined) : undefined)
const rangeEnd = computed(() => exportRange.value === 'range' ? (exportTo.value || undefined) : undefined)

async function downloadMarkdown() {
  exportMenuOpen.value = false
  const url = entriesApi.exportMarkdownUrl(rangeStart.value, rangeEnd.value)
  const resp = await fetch(url)
  const blob = await resp.blob()
  await saveFile({ data: blob, defaultName: 'lifelogr-export.zip', filters: [{ name: 'ZIP', extensions: ['zip'] }] })
  emit('toast', 'success', 'ZIP export saved')
}
async function downloadHtmlExport() {
  exportMenuOpen.value = false; exportingHtml.value = true
  try {
    const html = await exportHtml(rangeStart.value, rangeEnd.value)
    const blob = new Blob([html], { type: 'text/html' })
    await saveFile({ data: blob, defaultName: 'lifelogr-export.html', filters: [{ name: 'HTML', extensions: ['html'] }] })
    emit('toast', 'success', 'HTML export saved')
  } catch (e: unknown) { emit('toast', 'error', `HTML export failed: ${errMsg(e)}`) }
  finally { exportingHtml.value = false }
}
async function downloadPdfExport() {
  exportMenuOpen.value = false
  const url = getExportPdfUrl(rangeStart.value, rangeEnd.value)
  const resp = await fetch(url)
  const blob = await resp.blob()
  await saveFile({ data: blob, defaultName: 'lifelogr-export.pdf', filters: [{ name: 'PDF', extensions: ['pdf'] }] })
}
async function downloadDiarium() {
  exportMenuOpen.value = false; exportingDiarium.value = true
  try {
    const json = await exportDiarium(rangeStart.value, rangeEnd.value)
    const blob = new Blob([json], { type: 'application/json' })
    await saveFile({ data: blob, defaultName: 'lifelogr-export.json', filters: [{ name: 'JSON', extensions: ['json'] }] })
    emit('toast', 'success', 'Diarium JSON export saved')
  } catch (e: unknown) { emit('toast', 'error', `Diarium export failed: ${errMsg(e)}`) }
  finally { exportingDiarium.value = false }
}
async function downloadDiariumDb() {
  exportMenuOpen.value = false; exportingDiariumDb.value = true
  try {
    const url = getExportDiariumDbUrl(rangeStart.value, rangeEnd.value)
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    await saveFile({ data: blob, defaultName: 'lifelogr-export.diary', filters: [{ name: 'Diarium', extensions: ['diary'] }] })
    emit('toast', 'success', '.diary export saved')
  } catch (e: unknown) { emit('toast', 'error', `.diary export failed: ${errMsg(e)}`) }
  finally { exportingDiariumDb.value = false }
}

// ── Maintenance ──
const deduplicating = ref(false)
const vacuuming = ref(false)
const checkingIntegrity = ref(false)

async function handleDeduplicate() {
  deduplicating.value = true
  try {
    const r = await entriesApi.deduplicate()
    if (r.duplicates_removed === 0) emit('toast', 'info', 'No duplicates found')
    else emit('toast', 'success', `Removed ${r.duplicates_removed} duplicate${r.duplicates_removed > 1 ? 's' : ''} across ${r.groups_found} group${r.groups_found > 1 ? 's' : ''}`)
  } catch (e: unknown) { emit('toast', 'error', `Deduplicate failed: ${errMsg(e)}`) }
  finally { deduplicating.value = false }
}
async function handleVacuum() {
  vacuuming.value = true
  try {
    const r = await vacuumDatabase()
    emit('toast', 'success', `Database compacted — ${formatBytes(r.reclaimed_bytes)} reclaimed`)
    await loadAppSettings()
  } catch (e: unknown) { emit('toast', 'error', `Vacuum failed: ${errMsg(e)}`) }
  finally { vacuuming.value = false }
}
async function handleIntegrityCheck() {
  checkingIntegrity.value = true
  try {
    const r = await checkIntegrity()
    if (r.status === 'ok') emit('toast', 'success', 'Database integrity: OK')
    else emit('toast', 'error', `Integrity check failed: ${r.message}`)
  } catch (e: unknown) { emit('toast', 'error', `Check failed: ${errMsg(e)}`) }
  finally { checkingIntegrity.value = false }
}
import type { Ref } from 'vue'

onMounted(() => { loadAppSettings() })
</script>

<template>
  <!-- Storage -->
  <SettingsSection title="Storage" :icon="HardDrive" description="Disk usage and entry statistics" setting-key="Storage">
    <div v-if="appSettings?.storage" class="grid grid-cols-2 gap-x-6 gap-y-2">
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
  <SettingsSection title="Import / Export" :icon="FileUp" description="Bring entries in or export your journal" setting-key="Export"
    card-class="divide-y divide-border">
    <!-- Import -->
    <div class="p-3">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Upload :size="13" class="text-text-muted shrink-0" aria-hidden="true" />
        <span class="text-[13px] text-text-secondary flex-1">Import entries</span>
        <SButton variant="primary" :disabled="importingZip" @click="handleImportZip">
          <Loader v-if="importingZip" :size="11" class="animate-spin" /> ZIP/JSON
        </SButton>
        <SButton variant="ghost" :disabled="importingHtml" @click="handleImportHtml">
          <Loader v-if="importingHtml" :size="11" class="animate-spin" /> HTML
        </SButton>
        <SButton variant="ghost" :disabled="importingDiarium" @click="handleImportDiarium">
          <Loader v-if="importingDiarium" :size="11" class="animate-spin" /> Diarium
        </SButton>
      </div>
    </div>
    <!-- Export -->
    <div class="p-3 space-y-2">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Download :size="13" class="text-text-muted shrink-0" aria-hidden="true" />
        <span class="text-[13px] text-text-secondary">Export</span>
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
      <p v-if="rangeError" class="text-[11px] text-danger pl-[25px]">{{ rangeError }}</p>

      <!-- Export as… dropdown (scales better than a wrapping row of buttons) -->
      <div class="relative pl-[25px]">
        <SButton variant="primary" :disabled="exportDisabled" @click="exportMenuOpen = !exportMenuOpen">
          <Download :size="12" /> Export as… <ChevronDown :size="11" />
        </SButton>
        <div v-if="exportMenuOpen"
          class="absolute z-20 mt-1 w-44 rounded-md border border-border bg-surface shadow-lg overflow-hidden">
          <button class="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-hover transition-colors flex items-center gap-2" @click="downloadMarkdown">
            <FileUp :size="12" /> Markdown ZIP
          </button>
          <button class="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-hover transition-colors flex items-center gap-2"
            :disabled="exportingHtml" @click="downloadHtmlExport">
            <Loader v-if="exportingHtml" :size="12" class="animate-spin" /><Download v-else :size="12" /> HTML
          </button>
          <button class="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-hover transition-colors flex items-center gap-2" @click="downloadPdfExport">
            <Download :size="12" /> PDF
          </button>
          <button class="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-hover transition-colors flex items-center gap-2"
            :disabled="exportingDiarium" @click="downloadDiarium">
            <Loader v-if="exportingDiarium" :size="12" class="animate-spin" /><Download v-else :size="12" /> Diarium JSON
          </button>
          <button class="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-hover transition-colors flex items-center gap-2"
            :disabled="exportingDiariumDb" @click="downloadDiariumDb">
            <Loader v-if="exportingDiariumDb" :size="12" class="animate-spin" /><Database v-else :size="12" /> Diarium .diary
          </button>
        </div>
      </div>
    </div>
  </SettingsSection>

  <!-- Maintenance -->
  <SettingsSection title="Maintenance" :icon="Wrench" description="Database maintenance and cleanup" setting-key="Compact database"
    card-class="divide-y divide-border">
    <div class="p-3">
      <SettingRow :icon="Copy" label="Remove duplicates"
        description="Collapses entries with identical date and body text.">
        <SButton variant="ghost" :disabled="deduplicating" @click="handleDeduplicate">
          <Loader v-if="deduplicating" :size="12" class="animate-spin" />
          {{ deduplicating ? 'Scanning…' : 'Deduplicate' }}
        </SButton>
      </SettingRow>
    </div>
    <div class="p-3">
      <SettingRow :icon="Database" label="Compact database"
        description="Reclaims unused space (VACUUM). May take a moment.">
        <SButton variant="ghost" :disabled="vacuuming" @click="handleVacuum">
          <Loader v-if="vacuuming" :size="12" class="animate-spin" />
          {{ vacuuming ? 'Compacting…' : 'Vacuum' }}
        </SButton>
      </SettingRow>
    </div>
    <div class="p-3">
      <SettingRow :icon="Shield" label="Check integrity"
        description="Verifies the SQLite database file is not corrupt.">
        <SButton variant="ghost" :disabled="checkingIntegrity" @click="handleIntegrityCheck">
          <Loader v-if="checkingIntegrity" :size="12" class="animate-spin" />
          {{ checkingIntegrity ? 'Checking…' : 'Check' }}
        </SButton>
      </SettingRow>
    </div>
  </SettingsSection>
</template>
