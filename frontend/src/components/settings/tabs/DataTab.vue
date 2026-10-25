<script setup lang="ts">
import { computed } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { HardDrive, FileUp, FileDown, Cloud, Wrench } from 'lucide-vue-next'
import StoragePanel from '../panels/StoragePanel.vue'
import ImportPanel from '../panels/ImportPanel.vue'
import ExportPanel from '../panels/ExportPanel.vue'
import BackupRestorePanel from '../panels/BackupRestorePanel.vue'
import MaintenancePanel from '../panels/MaintenancePanel.vue'

type ToastType = 'success' | 'error' | 'info'
const emit = defineEmits<{ toast: [type: ToastType, message: string] }>()

// Pre-overhaul pill ids mapped onto their new homes so a persisted
// 'lifelogr-data-backup-pill' doesn't render a blank panel after upgrading.
// Resolved on read (not written back in setup) — writing during setup races
// useLocalStorage's own initialization and can be clobbered by it.
const legacyPillIds: Record<string, string> = {
  'import-export': 'import',
  backups: 'backup-restore',
  diagnostics: 'maintenance',
}

const pills = [
  { id: 'import', label: 'Import', icon: FileUp },
  { id: 'export', label: 'Export', icon: FileDown },
  { id: 'backup-restore', label: 'Backup & Restore', icon: Cloud },
  { id: 'maintenance', label: 'Maintenance', icon: Wrench },
  { id: 'storage', label: 'Storage', icon: HardDrive },
] as const
const pillIds = new Set<string>(pills.map((p) => p.id))

const storedPill = useLocalStorage<string>('lifelogr-data-backup-pill', 'import')
const activePill = computed({
  get: () => {
    const raw = storedPill.value
    return legacyPillIds[raw] ?? (pillIds.has(raw) ? raw : 'import')
  },
  set: (id: string) => {
    storedPill.value = id
  },
})

function forward(type: ToastType, message: string) {
  emit('toast', type, message)
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- Pill sub-nav -->
    <div
      role="tablist"
      aria-label="Data settings sections"
      class="flex flex-wrap items-center gap-1 p-0.5 bg-surface border border-border rounded-md w-fit max-w-full"
    >
      <button
        v-for="pill in pills"
        :key="pill.id"
        role="tab"
        :aria-selected="activePill === pill.id"
        @click="activePill = pill.id"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded text-[12px] font-medium cursor-pointer transition-colors whitespace-nowrap"
        :class="
          activePill === pill.id
            ? 'bg-accent/15 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
      >
        <component :is="pill.icon" :size="13" aria-hidden="true" />
        {{ pill.label }}
      </button>
    </div>

    <!-- Panels -->
    <ImportPanel v-if="activePill === 'import'" @toast="forward" />
    <ExportPanel v-else-if="activePill === 'export'" @toast="forward" />
    <BackupRestorePanel
      v-else-if="activePill === 'backup-restore'"
      @toast="forward"
    />
    <MaintenancePanel
      v-else-if="activePill === 'maintenance'"
      @toast="forward"
    />
    <StoragePanel v-else-if="activePill === 'storage'" @toast="forward" />
  </div>
</template>
