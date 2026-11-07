<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  getSettings,
  exportRecoveryKit,
  importRecoveryKit,
} from '../../../api/settings'
import { KeyRound, AlertTriangle, ShieldCheck, Download, Upload, Loader } from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import SButton from '../shared/SButton.vue'
import { errMsg } from '../../../utils/errorMessage.ts'

const emit = defineEmits<{
  toast: [type: 'success' | 'error' | 'info', message: string]
}>()

const mediaEncryptionOn = ref(false)
const kitExportedAt = ref('')

onMounted(async () => {
  try {
    const s = await getSettings()
    mediaEncryptionOn.value = s.security.media_encryption_enabled
    kitExportedAt.value = s.security.recovery_kit_exported_at
  } catch {
    // flags stay at their safe defaults
  }
})

// ── Export ──
const exportBusy = ref(false)
const exportPassphrase = ref('')
const generatedCode = ref('')

function downloadKit(kit: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(kit, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'lifelogr-recovery.json'
  a.click()
  URL.revokeObjectURL(url)
}

async function handleExport() {
  exportBusy.value = true
  try {
    const result = await exportRecoveryKit(exportPassphrase.value || undefined)
    downloadKit(result.kit)
    kitExportedAt.value = new Date().toISOString()
    if (result.code) {
      generatedCode.value = result.code
      emit(
        'toast',
        'info',
        'Kit saved. Write down the recovery code — it is the only way to open the file.',
      )
    } else {
      emit('toast', 'success', 'Recovery kit saved — keep it somewhere safe.')
    }
    exportPassphrase.value = ''
  } catch (e: unknown) {
    emit('toast', 'error', `Export failed: ${errMsg(e)}`)
  } finally {
    exportBusy.value = false
  }
}

// ── Import ──
const importBusy = ref(false)
const importPassphrase = ref('')
const pendingKit = ref<Record<string, unknown> | null>(null)
const needsConfirm = ref(false)

function onKitFileChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  file
    .text()
    .then((text) => {
      pendingKit.value = JSON.parse(text) as Record<string, unknown>
      needsConfirm.value = false
      emit('toast', 'info', 'Kit loaded — enter its passphrase or recovery code.')
    })
    .catch(() => {
      pendingKit.value = null
      emit('toast', 'error', 'That file is not a valid recovery kit.')
    })
    .finally(() => {
      input.value = ''
    })
}

async function handleImport(confirmReplace = false) {
  if (!pendingKit.value || !importPassphrase.value) return
  importBusy.value = true
  try {
    const result = await importRecoveryKit(
      pendingKit.value,
      importPassphrase.value,
      confirmReplace,
    )
    if (result.status === 'confirm_replace') {
      needsConfirm.value = true
      emit(
        'toast',
        'info',
        'This kit holds a different key than the active one — confirm to replace it.',
      )
      return
    }
    needsConfirm.value = false
    pendingKit.value = null
    importPassphrase.value = ''
    emit(
      'toast',
      'success',
      result.status === 'unchanged'
        ? 'This kit matches the key already in use.'
        : 'Key restored — credentials and attachments are readable again.',
    )
  } catch (e: unknown) {
    emit('toast', 'error', `Import failed: ${errMsg(e)}`)
  } finally {
    importBusy.value = false
  }
}
</script>

<template>
  <SettingsSection
    title="Recovery Kit"
    :icon="ShieldCheck"
    description="A backup for the encryption key itself"
    setting-key="Recovery kit"
  >
    <div class="p-3 space-y-3">
      <div
        v-if="mediaEncryptionOn && !kitExportedAt"
        class="flex gap-2 p-2.5 rounded-md border border-amber-500/40 bg-amber-500/10 text-[12px]"
      >
        <AlertTriangle :size="15" class="shrink-0 mt-0.5 text-amber-500" />
        <p class="text-text-secondary">
          Encryption is in use but you have no recovery kit. If the key is lost
          (hardware failure, wiped data directory), encrypted attachments and
          stored cloud credentials cannot be recovered.
        </p>
      </div>

      <SettingRow
        :icon="Download"
        label="Export recovery kit"
        description="Saves lifelogr-recovery.json, wrapping the encryption key under a passphrase (or a generated recovery code). Store it somewhere safe — it is as sensitive as the key itself."
      >
        <div class="flex flex-col items-end gap-1.5">
          <input
            v-model="exportPassphrase"
            type="password"
            placeholder="Passphrase (optional)"
            class="px-2 py-1 text-[12px] bg-surface border border-border rounded w-40"
            :aria-label="'Recovery kit passphrase'"
          />
          <SButton variant="ghost" :disabled="exportBusy" @click="handleExport">
            <Loader v-if="exportBusy" :size="12" class="animate-spin" />
            {{ exportBusy ? 'Exporting…' : 'Export' }}
          </SButton>
        </div>
      </SettingRow>

      <div
        v-if="generatedCode"
        class="flex flex-col gap-1.5 p-2.5 rounded-md border border-border bg-surface/50"
      >
        <p class="text-[11px] text-text-muted">
          Recovery code — the only way to open this kit. Print or write it down:
        </p>
        <code class="text-[13px] font-mono tracking-wider text-accent select-all">{{
          generatedCode
        }}</code>
      </div>

      <SettingRow
        :icon="Upload"
        label="Restore from recovery kit"
        description="After losing the key (new machine, wiped data directory): load the kit file, enter its passphrase or recovery code, and the key is verified against your data before it is installed."
      >
        <div class="flex flex-col items-end gap-1.5">
          <input
            type="file"
            accept="application/json,.json"
            class="text-[11px] text-text-secondary file:mr-2 file:px-2 file:py-0.5 file:rounded file:border file:border-border file:bg-surface file:text-[11px]"
            aria-label="Recovery kit file"
            @change="onKitFileChosen"
          />
          <input
            v-model="importPassphrase"
            type="password"
            placeholder="Passphrase or recovery code"
            class="px-2 py-1 text-[12px] bg-surface border border-border rounded w-44"
            :disabled="!pendingKit"
            :aria-label="'Kit passphrase or recovery code'"
          />
          <SButton
            variant="ghost"
            :disabled="importBusy || !pendingKit || !importPassphrase"
            @click="handleImport(false)"
          >
            <Loader v-if="importBusy" :size="12" class="animate-spin" />
            {{ importBusy ? 'Verifying…' : 'Restore key' }}
          </SButton>
          <SButton
            v-if="needsConfirm"
            variant="ghost"
            :disabled="importBusy"
            @click="handleImport(true)"
          >
            Replace the active key anyway
          </SButton>
        </div>
      </SettingRow>

      <p v-if="kitExportedAt" class="text-[11px] text-text-muted flex items-center gap-1.5">
        <KeyRound :size="12" />
        Last exported {{ new Date(kitExportedAt).toLocaleString() }}
      </p>
    </div>
  </SettingsSection>
</template>
