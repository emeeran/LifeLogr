<script setup lang="ts">
import { ref } from 'vue'
import { entriesApi } from '../../../api/entries'
import { notesApi } from '../../../api/notes'
import { useEntriesStore } from '../../../stores/entries'
import { useJobProgress } from '../../../composables/useJobProgress'
import { pickFile } from '../../../utils/fileDialog'
import {
  Upload,
  Loader,
  FileUp,
  FileDown,
  FileJson,
  FileSpreadsheet,
  Database,
  ChevronDown,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SButton from '../shared/SButton.vue'
import OperationProgress from '../../common/OperationProgress.vue'
import { errMsg } from '../../../utils/errorMessage.ts'

const emit = defineEmits<{
  toast: [type: 'success' | 'error' | 'info', message: string]
}>()

const entriesStore = useEntriesStore()

// Uploads parse synchronously; the insert loop runs as a polled job so large
// imports show per-row progress instead of a bare spinner. Entries and notes
// share one progress bar — the label names whichever import is active.
const importing = ref(false)
const importMenuOpen = ref(false)
const notesImportMenuOpen = ref(false)
const importProgress = useJobProgress()
const importLabel = ref('Import')

async function runJobImport(jobId: string, label: string) {
  importLabel.value = label
  const final = await importProgress.run(jobId)
  if (!final) return
  entriesStore.refreshAll()
  if (final.status === 'done') {
    emit('toast', 'success', final.detail ?? `${label} complete`)
  } else {
    emit('toast', 'error', `${label} failed: ${final.error ?? 'unknown'}`)
  }
}

async function runImport(accept: string) {
  importMenuOpen.value = false
  const file = await pickFile({ accept })
  if (!file) return
  importing.value = true
  try {
    const started = await entriesApi.importFileJob(file)
    await runJobImport(started.job_id, 'Import')
  } catch (e: unknown) {
    emit('toast', 'error', `Import failed: ${errMsg(e)}`)
  } finally {
    importing.value = false
  }
}

async function runNotesImport(accept: string) {
  notesImportMenuOpen.value = false
  const file = await pickFile({ accept })
  if (!file) return
  importing.value = true
  try {
    const started = await notesApi.importFileJob(file)
    await runJobImport(started.job_id, 'Notes import')
  } catch (e: unknown) {
    emit('toast', 'error', `Import failed: ${errMsg(e)}`)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <SettingsSection
    title="Import"
    :icon="Upload"
    description="Bring entries and notes in from other apps or backups"
    setting-key="Export"
    card-class="divide-y divide-border"
  >
    <!-- Entries -->
    <div class="p-3">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Upload
          :size="13"
          class="text-text-muted shrink-0"
          aria-hidden="true"
        />
        <span class="text-[13px] text-text-secondary flex-1"
          >Import entries</span
        >
        <div class="relative">
          <SButton
            variant="primary"
            :disabled="importing"
            @click="importMenuOpen = !importMenuOpen"
          >
            <Loader v-if="importing" :size="11" class="animate-spin" />
            <Upload v-else :size="12" /> Import… <ChevronDown :size="11" />
          </SButton>
          <div
            v-if="importMenuOpen"
            class="absolute z-20 right-0 mt-1 w-48 rounded-md border border-border bg-surface shadow-lg overflow-hidden"
          >
            <button class="import-item" @click="runImport('.diary,.json')">
              <Database :size="12" /> Diarium (.diary / .json)
            </button>
            <button class="import-item" @click="runImport('.zip')">
              <FileUp :size="12" /> Day One (.zip)
            </button>
            <button class="import-item" @click="runImport('.csv')">
              <FileSpreadsheet :size="12" /> CSV (.csv)
            </button>
            <button class="import-item" @click="runImport('.json')">
              <FileJson :size="12" /> JSON (.json)
            </button>
            <button class="import-item" @click="runImport('.zip,.md')">
              <FileDown :size="12" /> Markdown (.zip / .md)
            </button>
            <button class="import-item" @click="runImport('.html,.htm')">
              <FileDown :size="12" /> HTML
            </button>
          </div>
        </div>
      </div>
      <p class="text-[11px] text-text-muted pl-[25px] mt-1">
        Duplicate entries (same date + body) are skipped automatically.
      </p>
    </div>

    <!-- Notes -->
    <div class="p-3">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Upload
          :size="13"
          class="text-text-muted shrink-0"
          aria-hidden="true"
        />
        <span class="text-[13px] text-text-secondary flex-1">Import notes</span>
        <div class="relative">
          <SButton
            variant="primary"
            :disabled="importing"
            @click="notesImportMenuOpen = !notesImportMenuOpen"
          >
            <Loader v-if="importing" :size="11" class="animate-spin" />
            <Upload v-else :size="12" /> Import… <ChevronDown :size="11" />
          </SButton>
          <div
            v-if="notesImportMenuOpen"
            class="absolute z-20 right-0 mt-1 w-48 rounded-md border border-border bg-surface shadow-lg overflow-hidden"
          >
            <button class="import-item" @click="runNotesImport('.json')">
              <FileJson :size="12" /> LifeLogr JSON
            </button>
            <button class="import-item" @click="runNotesImport('.zip')">
              <FileUp :size="12" /> Markdown ZIP
            </button>
          </div>
        </div>
      </div>
      <p class="text-[11px] text-text-muted pl-[25px] mt-1">
        Round-trips with the notes exports on the Export pill. Encrypted notes
        import as plain text.
      </p>
      <OperationProgress
        :job="importProgress.job.value"
        :label="importLabel"
        class="pl-[25px] mt-1.5"
      />
    </div>
  </SettingsSection>
</template>

<style scoped>
.import-item {
  width: 100%;
  text-align: left;
  padding: 0.375rem 0.75rem;
  font-size: 12px;
  color: var(--color-text-primary, inherit);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: background-color 0.15s;
}
.import-item:hover {
  background-color: var(--color-surface-hover, rgba(255, 255, 255, 0.05));
}
</style>
