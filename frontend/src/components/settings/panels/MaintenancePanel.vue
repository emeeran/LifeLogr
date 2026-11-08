<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { entriesApi } from '../../../api/entries'
import {
  vacuumDatabase,
  encryptMedia,
  getSettings,
  type EncryptMediaReport,
} from '../../../api/settings'
import { useSystemHealthStore } from '../../../stores/systemHealth'
import {
  Database,
  Copy,
  Wrench,
  Loader,
  RefreshCw,
  Search,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Type,
  Lock,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import SButton from '../shared/SButton.vue'
import { errorMessage } from '../../../utils/errorMessage'

const emit = defineEmits<{
  toast: [type: 'success' | 'error' | 'info', message: string]
}>()

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const deduplicating = ref(false)
const vacuuming = ref(false)

async function handleDeduplicate() {
  deduplicating.value = true
  try {
    const r = await entriesApi.deduplicate()
    if (r.duplicates_removed === 0) emit('toast', 'info', 'No duplicates found')
    else
      emit(
        'toast',
        'success',
        `Removed ${r.duplicates_removed} duplicate${r.duplicates_removed > 1 ? 's' : ''} across ${r.groups_found} group${r.groups_found > 1 ? 's' : ''}`,
      )
  } catch (e: unknown) {
    emit('toast', 'error', `Deduplicate failed: ${errorMessage(e)}`)
  } finally {
    deduplicating.value = false
  }
}
// ── Fill missing titles (auto-title backfill) ──
// Two-step on purpose: the first click only reports how many entries would gain
// a title, the second writes. Titles never overwrite a non-empty one.
const titlesBusy = ref(false)
const titlesPending = ref<number | null>(null)

async function handleBackfillTitles() {
  titlesBusy.value = true
  try {
    if (titlesPending.value == null) {
      const preview = await entriesApi.backfillTitles(true)
      titlesPending.value = preview.candidates
      if (preview.candidates === 0) {
        emit('toast', 'info', 'Every titled entry already has one')
        titlesPending.value = null
      }
      return
    }
    const result = await entriesApi.backfillTitles(false)
    emit(
      'toast',
      'success',
      `Filled ${result.updated} title${result.updated === 1 ? '' : 's'}`,
    )
    titlesPending.value = null
  } catch (e: unknown) {
    emit('toast', 'error', `Title backfill failed: ${errorMessage(e)}`)
  } finally {
    titlesBusy.value = false
  }
}

async function handleVacuum() {
  vacuuming.value = true
  try {
    const r = await vacuumDatabase()
    emit(
      'toast',
      'success',
      `Database compacted — ${formatBytes(r.reclaimed_bytes)} reclaimed`,
    )
  } catch (e: unknown) {
    emit('toast', 'error', `Vacuum failed: ${errorMessage(e)}`)
  } finally {
    vacuuming.value = false
  }
}

// ── Encrypt attachments of encrypted items ──
// Two-step like the title backfill: preview first, second click writes. Only
// shown when media encryption is enabled (the ENCRYPT_MEDIA rollout flag) —
// the backend refuses the job otherwise. Resumable: already-encrypted files
// are skipped, so a rerun is always safe.
const mediaEncryptionOn = ref(false)
const encryptBusy = ref(false)
const encryptPreview = ref<EncryptMediaReport | null>(null)

async function handleEncryptMedia() {
  encryptBusy.value = true
  try {
    if (encryptPreview.value == null) {
      const preview = await encryptMedia(true)
      if (preview.candidates === 0 && preview.stale_thumbs === 0) {
        emit('toast', 'info', 'Everything is already encrypted')
      } else {
        encryptPreview.value = preview
      }
      return
    }
    const result = await encryptMedia(false)
    if (result.errors.length > 0) {
      emit(
        'toast',
        'error',
        `Encrypted ${result.updated} file(s), ${result.errors.length} failed — they were left untouched`,
      )
    } else {
      emit(
        'toast',
        'success',
        `Encrypted ${result.updated} attachment${result.updated === 1 ? '' : 's'}${
          result.thumbs_purged > 0
            ? `, cleaned ${result.thumbs_purged} old thumbnail${result.thumbs_purged === 1 ? '' : 's'}`
            : ''
        }`,
      )
    }
    encryptPreview.value = null
  } catch (e: unknown) {
    emit('toast', 'error', `Encryption failed: ${errorMessage(e)}`)
  } finally {
    encryptBusy.value = false
  }
}
// ── Startup system check (absorbed from the former Diagnostics pill) ──
const health = useSystemHealthStore()
const checks = computed(() => health.report?.checks ?? [])
const ranAt = computed(() =>
  health.report?.ran_at ? new Date(health.report.ran_at).toLocaleString() : '—',
)

onMounted(() => {
  if (!health.loaded) health.load()
  getSettings()
    .then((s) => {
      mediaEncryptionOn.value = s.security.media_encryption_enabled
    })
    .catch(() => mediaEncryptionOn.value = false)
})

async function recheck() {
  await health.refresh()
  emit(
    'toast',
    health.hasIssues ? 'error' : 'success',
    health.hasIssues
      ? `Still ${health.issueCount} issue(s).`
      : 'All checks passed.',
  )
}

async function rebuildIndex() {
  await health.rebuildIndex()
  emit('toast', 'success', 'Search index rebuilt.')
}
</script>

<template>
  <SettingsSection
    title="Maintenance"
    :icon="Wrench"
    description="Database maintenance and cleanup"
    setting-key="Compact database"
    card-class="divide-y divide-border"
  >
    <div class="p-3">
      <SettingRow
        :icon="Copy"
        label="Remove duplicates"
        description="Collapses entries with identical date and body text."
      >
        <SButton
          variant="ghost"
          :disabled="deduplicating"
          @click="handleDeduplicate"
        >
          <Loader v-if="deduplicating" :size="12" class="animate-spin" />
          {{ deduplicating ? 'Scanning…' : 'Deduplicate' }}
        </SButton>
      </SettingRow>
    </div>
    <div class="p-3">
      <SettingRow
        :icon="Type"
        label="Fill missing titles"
        :description="
          titlesPending == null
            ? 'Use the first meaningful line of the body as the title where none is set. Never overwrites an existing title.'
            : `${titlesPending} entr${titlesPending === 1 ? 'y' : 'ies'} would gain a title — click again to apply.`
        "
      >
        <SButton
          variant="ghost"
          :disabled="titlesBusy"
          @click="handleBackfillTitles"
        >
          <Loader v-if="titlesBusy" :size="12" class="animate-spin" />
          <template v-if="titlesBusy">Working…</template>
          <template v-else-if="titlesPending != null">
            Apply to {{ titlesPending }}
          </template>
          <template v-else>Preview</template>
        </SButton>
      </SettingRow>
    </div>
    <div class="p-3">
      <SettingRow
        :icon="Database"
        label="Compact database"
        description="Reclaims unused space (VACUUM). May take a moment."
      >
        <SButton variant="ghost" :disabled="vacuuming" @click="handleVacuum">
          <Loader v-if="vacuuming" :size="12" class="animate-spin" />
          {{ vacuuming ? 'Compacting…' : 'Vacuum' }}
        </SButton>
      </SettingRow>
    </div>
    <div v-if="mediaEncryptionOn" class="p-3">
      <SettingRow
        :icon="Lock"
        label="Encrypt attachments of encrypted items"
        :description="
          encryptPreview == null
            ? 'Encrypts photos, audio and documents attached to encrypted entries and notes so they are unreadable on disk and in backups. Runs a preview first; safe to rerun.'
            : `${encryptPreview.candidates} file${encryptPreview.candidates === 1 ? '' : 's'} (${formatBytes(encryptPreview.plaintext_bytes)}${
                encryptPreview.stale_thumbs > 0
                  ? `, ${encryptPreview.stale_thumbs} old thumbnail${encryptPreview.stale_thumbs === 1 ? '' : 's'}`
                  : ''
              }) — click again to apply.`
        "
      >
        <SButton variant="ghost" :disabled="encryptBusy" @click="handleEncryptMedia">
          <Loader v-if="encryptBusy" :size="12" class="animate-spin" />
          <template v-if="encryptBusy">Working…</template>
          <template v-else-if="encryptPreview != null">Apply</template>
          <template v-else>Preview</template>
        </SButton>
      </SettingRow>
    </div>
  </SettingsSection>

  <!-- Startup system check -->
  <SettingsSection
    title="System Check"
    :icon="RefreshCw"
    description="Startup app-integrity report"
    setting-key="System check"
  >
    <div class="p-3 space-y-2">
      <div class="flex items-center justify-between gap-3">
        <p class="text-xs text-text-muted">Last run {{ ranAt }}</p>
        <div class="flex items-center gap-2">
          <SButton
            variant="ghost"
            :icon="Search"
            :disabled="health.refreshing"
            @click="rebuildIndex"
          >
            Rebuild index
          </SButton>
          <SButton
            variant="ghost"
            :disabled="health.refreshing"
            @click="recheck"
          >
            <Loader
              v-if="health.refreshing"
              :size="12"
              class="animate-spin"
            />
            Re-check
          </SButton>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 text-[11px]">
        <span
          class="px-2 py-0.5 rounded text-[11px] font-medium bg-green-500/15 text-green-700 dark:bg-green-500/20 dark:text-green-300 border border-green-500/30"
          >OK {{ health.summary.ok }}</span
        >
        <span
          class="px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/15 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300 border border-amber-500/30"
          >Warn {{ health.summary.warn }}</span
        >
        <span
          class="px-2 py-0.5 rounded text-[11px] font-medium bg-red-500/15 text-red-700 dark:bg-red-500/20 dark:text-red-300 border border-red-500/30"
          >Error {{ health.summary.error }}</span
        >
      </div>

      <ul class="space-y-1.5">
        <li
          v-for="c in checks"
          :key="c.id"
          class="flex gap-2 p-2 rounded-md border border-border bg-surface/40"
        >
          <component
            :is="
              c.status === 'ok'
                ? CheckCircle2
                : c.status === 'warn'
                  ? AlertTriangle
                  : AlertCircle
            "
            :size="15"
            :class="
              c.status === 'ok'
                ? 'text-green-500 dark:text-green-400'
                : c.status === 'warn'
                  ? 'text-amber-500 dark:text-amber-400'
                  : 'text-red-500 dark:text-red-400'
            "
            class="shrink-0 mt-0.5"
          />
          <div class="min-w-0">
            <div class="text-xs font-medium text-text-primary">
              {{ c.label }}
            </div>
            <div class="text-xs text-text-secondary break-words">
              {{ c.detail }}
            </div>
            <div
              v-if="c.hint"
              class="text-xs font-medium text-amber-600 dark:text-amber-400"
            >
              → {{ c.hint }}
            </div>
          </div>
        </li>
      </ul>
    </div>
  </SettingsSection>
</template>
