<script setup lang="ts">
import { ref, computed } from 'vue'
import { entriesApi } from '../../../api/entries'
import { notesApi } from '../../../api/notes'
import {
  exportHtml,
  getExportPdfUrl,
  exportDiarium,
  getExportDiariumDbUrl,
} from '../../../api/data'
import { useJobProgress } from '../../../composables/useJobProgress'
import { jobsApi } from '../../../api/jobs'
import { saveFile } from '../../../utils/fileDialog'
import {
  Download,
  FileUp,
  FileDown,
  FileJson,
  FileSpreadsheet,
  FileText,
  Database,
  NotebookPen,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SButton from '../shared/SButton.vue'
import OperationProgress from '../../common/OperationProgress.vue'
import { errorMessage } from '../../../utils/errorMessage'

const emit = defineEmits<{
  toast: [type: 'success' | 'error' | 'info', message: string]
}>()

// ── Date range (entries formats) ──
const exportRange = ref<'all' | 'range'>('all')
const exportFrom = ref('')
const exportTo = ref('')

const rangeError = computed(() => {
  if (exportRange.value !== 'range') return ''
  if (!exportFrom.value || !exportTo.value) return ''
  return exportFrom.value > exportTo.value
    ? 'Start date must be before end date'
    : ''
})
const exportDisabled = computed(
  () =>
    !!rangeError.value ||
    (exportRange.value === 'range' && (!exportFrom.value || !exportTo.value)),
)
const rangeStart = computed(() =>
  exportRange.value === 'range' ? exportFrom.value || undefined : undefined,
)
const rangeEnd = computed(() =>
  exportRange.value === 'range' ? exportTo.value || undefined : undefined,
)

// ── Shared progress ──
// Media-carrying exports build as polled jobs (per-file progress), then the
// finished archive downloads once from the job's result endpoint.
const exportProgress = useJobProgress()
const exportLabel = ref('Export')

function done(label: string) {
  emit('toast', 'success', `${label} saved`)
}

/** Every row click funnels through here so failures surface as a toast
 *  instead of an unhandled rejection. */
async function guard(label: string, fn: () => Promise<void>) {
  try {
    await fn()
  } catch (e: unknown) {
    emit('toast', 'error', `${label} failed: ${errorMessage(e)}`)
  }
}

async function downloadViaJob(
  url: string,
  label: string,
  saveOpts: { defaultName: string; filters: { name: string; extensions: string[] }[] },
) {
  exportLabel.value = label
  const started = await jobsApi.startExport(url)
  const final = await exportProgress.run(started.job_id)
  if (!final) return
  if (final.status !== 'done') {
    emit('toast', 'error', `${label} failed: ${final.error ?? 'unknown'}`)
    return
  }
  const blob = await jobsApi.result(started.job_id)
  await saveFile({ data: blob, ...saveOpts })
  done(label)
}

async function downloadBlob(
  url: string,
  label: string,
  saveOpts: { defaultName: string; filters: { name: string; extensions: string[] }[] },
) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  await saveFile({ data: await resp.blob(), ...saveOpts })
  done(label)
}

// ── Entries formats (each row states what it carries) ──
// Native archive: full-fidelity entries + media + notes, re-importable as-is
// — the portable export (vs the full-instance .tar.gz under Backup & Restore).
async function downloadArchive() {
  await downloadViaJob(
    entriesApi.exportArchiveUrl(rangeStart.value, rangeEnd.value),
    'Archive export',
    {
      defaultName: 'lifelogr-archive.zip',
      filters: [{ name: 'ZIP', extensions: ['zip'] }],
    },
  )
}
async function downloadMarkdown() {
  await downloadViaJob(
    entriesApi.exportMarkdownUrl(rangeStart.value, rangeEnd.value),
    'ZIP export',
    {
      defaultName: 'lifelogr-export.zip',
      filters: [{ name: 'ZIP', extensions: ['zip'] }],
    },
  )
}
async function downloadHtmlZip() {
  await downloadViaJob(
    entriesApi.exportHtmlZipUrl(rangeStart.value, rangeEnd.value),
    'HTML archive export',
    {
      defaultName: 'lifelogr-export-html.zip',
      filters: [{ name: 'ZIP', extensions: ['zip'] }],
    },
  )
}
async function downloadDiariumDb() {
  await downloadViaJob(
    getExportDiariumDbUrl(rangeStart.value, rangeEnd.value),
    '.diary export',
    {
      defaultName: 'lifelogr-export.diary',
      filters: [{ name: 'Diarium', extensions: ['diary'] }],
    },
  )
}
async function downloadJsonExport() {
  await downloadBlob(entriesApi.exportJsonUrl(rangeStart.value, rangeEnd.value), 'JSON export', {
    defaultName: 'lifelogr-export.json',
    filters: [{ name: 'JSON', extensions: ['json'] }],
  })
}
async function downloadHtmlExport() {
  exportLabel.value = 'HTML export'
  const html = await exportHtml(rangeStart.value, rangeEnd.value)
  const blob = new Blob([html], { type: 'text/html' })
  await saveFile({
    data: blob,
    defaultName: 'lifelogr-export.html',
    filters: [{ name: 'HTML', extensions: ['html'] }],
  })
  done('HTML export')
}
async function downloadPdfExport() {
  await downloadBlob(getExportPdfUrl(rangeStart.value, rangeEnd.value), 'PDF export', {
    defaultName: 'lifelogr-export.pdf',
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  })
}
async function downloadDiarium() {
  exportLabel.value = 'Diarium JSON export'
  const json = await exportDiarium(rangeStart.value, rangeEnd.value)
  const blob = new Blob([json], { type: 'application/json' })
  await saveFile({
    data: blob,
    defaultName: 'lifelogr-export.json',
    filters: [{ name: 'JSON', extensions: ['json'] }],
  })
  done('Diarium JSON export')
}
// Daylio-format CSV — the migration format Diarium actually documents an
// importer for (Settings → Database → Migrate from other app → CSV).
async function downloadDaylioCsv() {
  await downloadBlob(entriesApi.exportDaylioCsvUrl(rangeStart.value, rangeEnd.value), 'CSV export', {
    defaultName: 'lifelogr-export.csv',
    filters: [{ name: 'CSV', extensions: ['csv'] }],
  })
}

// Day One ZIP — Diarium's "Migrate from other app → Day One" is the only
// import route that carries attachments (matched by md5-named archive members).
const dayoneScope = ref<'new' | 'all'>('new')
async function downloadDayOne() {
  await downloadViaJob(
    entriesApi.exportDayOneUrl(
      rangeStart.value,
      rangeEnd.value,
      dayoneScope.value,
    ),
    'Day One export',
    {
      defaultName: 'lifelogr-dayone.zip',
      filters: [{ name: 'ZIP', extensions: ['zip'] }],
    },
  )
}

// ── Notes formats ──
async function downloadNotesMarkdown() {
  exportLabel.value = 'Notes ZIP export'
  await downloadBlob(notesApi.exportMarkdownUrl(), 'Notes ZIP export', {
    defaultName: 'lifelogr-notes.zip',
    filters: [{ name: 'ZIP', extensions: ['zip'] }],
  })
}
async function downloadNotesJson() {
  exportLabel.value = 'Notes JSON export'
  await downloadBlob(notesApi.exportJsonUrl(), 'Notes JSON export', {
    defaultName: 'lifelogr-notes.json',
    filters: [{ name: 'JSON', extensions: ['json'] }],
  })
}
async function downloadNotesHtml() {
  exportLabel.value = 'Notes HTML export'
  const resp = await fetch(notesApi.exportHtmlUrl())
  const html = await resp.text()
  const blob = new Blob([html], { type: 'text/html' })
  await saveFile({
    data: blob,
    defaultName: 'lifelogr-notes.html',
    filters: [{ name: 'HTML', extensions: ['html'] }],
  })
  done('Notes HTML export')
}
</script>

<template>
  <SettingsSection
    title="Export"
    :icon="Download"
    description="Download your journal in the format you need"
    setting-key="Export"
    card-class="divide-y divide-border"
  >
    <!-- Range + explainer -->
    <div class="p-3">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Download
          :size="13"
          class="text-text-muted shrink-0"
          aria-hidden="true"
        />
        <span class="text-[13px] text-text-secondary">Date range</span>
        <label
          class="flex items-center gap-1 text-[11px] cursor-pointer text-text-muted"
        >
          <input
            type="radio"
            v-model="exportRange"
            value="all"
            class="accent-accent"
          />
          All
        </label>
        <label
          class="flex items-center gap-1 text-[11px] cursor-pointer text-text-muted"
        >
          <input
            type="radio"
            v-model="exportRange"
            value="range"
            class="accent-accent"
          />
          Range
        </label>
        <template v-if="exportRange === 'range'">
          <input v-model="exportFrom" type="date" class="settings-input w-28" />
          <input v-model="exportTo" type="date" class="settings-input w-28" />
        </template>
      </div>
      <p v-if="rangeError" class="text-[11px] text-danger pl-[25px] mt-1">
        {{ rangeError }}
      </p>
      <p class="text-[11px] text-text-muted pl-[25px] mt-1">
        <span class="text-text-secondary">Portable export</span> (Archive ZIP,
        .diary) carries entries <em>and</em> their media and imports into
        lifelogr or Diarium — use it to move data. The
        <span class="text-text-secondary">full-instance backup</span> (a
        .tar.gz under Backup &amp; Restore) copies the entire database for
        restoring this installation.
      </p>
    </div>

    <!-- Entries formats -->
    <div class="p-3 space-y-1.5">
      <div class="flex items-center gap-2.5 mb-1.5">
        <FileUp :size="13" class="text-text-muted shrink-0" aria-hidden="true" />
        <span class="text-[13px] text-text-secondary">Entries</span>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Archive ZIP
            <span class="carries">entries · media · tags · events · notes</span>
          </div>
          <p class="text-[11px] text-text-muted">
            The complete portable export — re-imports into any lifelogr
            instance with media links, note attachments and events intact.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('Archive export', downloadArchive)"
        >
          <Download :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Diarium .diary
            <span class="carries">entries · media · tags · trackers · events</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Native Diarium database — open it directly in the Diarium app.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('.diary export', downloadDiariumDb)"
        >
          <Database :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Day One ZIP (Diarium push)
            <span class="carries">entries · media · tags</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Import via Diarium's <em>Migrate from other app → Day One</em> — the
            one route that carries photos and attachments. "Only new" skips days
            Diarium already has.
          </p>
        </div>
        <select
          v-model="dayoneScope"
          class="settings-input w-24 text-[11px]"
          :disabled="exportDisabled"
        >
          <option value="new">Only new</option>
          <option value="all">All</option>
        </select>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('Day One export', downloadDayOne)"
        >
          <FileDown :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Markdown ZIP
            <span class="carries">entries · media · tags</span>
          </div>
          <p class="text-[11px] text-text-muted">
            One .md file per entry with YAML frontmatter — reads in editors
            and Obsidian-style vaults.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('ZIP export', downloadMarkdown)"
        >
          <FileDown :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            HTML archive
            <span class="carries">entries · media</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Styled offline page — unzip and browse without lifelogr.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('HTML archive export', downloadHtmlZip)"
        >
          <FileDown :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            JSON
            <span class="carries">entries · tags</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Structured document that round-trips through the JSON importer.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('JSON export', downloadJsonExport)"
        >
          <FileJson :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            HTML
            <span class="carries">entries</span>
          </div>
          <p class="text-[11px] text-text-muted">Single self-contained page.</p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('HTML export', downloadHtmlExport)"
        >
          <FileText :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            PDF
            <span class="carries">entries</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Print-ready document for sharing or archiving on paper.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('PDF export', downloadPdfExport)"
        >
          <FileText :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Diarium JSON
            <span class="carries">entries · tags</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Text of every entry for Diarium's JSON import path.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('Diarium JSON export', downloadDiarium)"
        >
          <FileJson :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Diarium CSV (Daylio)
            <span class="carries">entries · mood</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Daylio-format CSV — the migration format Diarium documents an
            importer for.
          </p>
        </div>
        <SButton
          variant="ghost"
          :disabled="exportDisabled"
          @click="guard('CSV export', downloadDaylioCsv)"
        >
          <FileSpreadsheet :size="12" /> Export
        </SButton>
      </div>

      <OperationProgress
        :job="exportProgress.job.value"
        :label="exportLabel"
        class="mt-1.5"
      />
    </div>

    <!-- Notes formats -->
    <div class="p-3 space-y-1.5">
      <div class="flex items-center gap-2.5 mb-1.5">
        <NotebookPen
          :size="13"
          class="text-text-muted shrink-0"
          aria-hidden="true"
        />
        <span class="text-[13px] text-text-secondary">Notes</span>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            Markdown ZIP <span class="carries">notes · folders</span>
          </div>
          <p class="text-[11px] text-text-muted">
            One .md file per note, foldered — round-trips with the importer.
          </p>
        </div>
        <SButton variant="ghost" @click="guard('Notes ZIP export', downloadNotesMarkdown)">
          <FileDown :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            JSON <span class="carries">notes · folders</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Structured notes document that round-trips through the importer.
          </p>
        </div>
        <SButton variant="ghost" @click="guard('Notes JSON export', downloadNotesJson)">
          <FileJson :size="12" /> Export
        </SButton>
      </div>

      <div class="format-row">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] text-text-primary">
            HTML <span class="carries">notes</span>
          </div>
          <p class="text-[11px] text-text-muted">
            Single page of every note. Encrypted notes export a placeholder
            body — ciphertext is never written.
          </p>
        </div>
        <SButton variant="ghost" @click="guard('Notes HTML export', downloadNotesHtml)">
          <FileText :size="12" /> Export
        </SButton>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.format-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.375rem 0;
}
.format-row + .format-row {
  border-top: 1px solid var(--color-border, rgba(128, 128, 128, 0.2));
}
.carries {
  margin-left: 0.375rem;
  font-size: 10px;
  color: var(--color-text-muted, inherit);
}
</style>
