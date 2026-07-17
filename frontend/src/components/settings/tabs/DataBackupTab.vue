<script setup lang="ts">
import { useLocalStorage } from "@vueuse/core";
import { HardDrive, FileUp, Cloud, Wrench } from "lucide-vue-next";
import StoragePanel from "../panels/StoragePanel.vue";
import ImportExportPanel from "../panels/ImportExportPanel.vue";
import BackupTab from "./BackupTab.vue";
import MaintenancePanel from "../panels/MaintenancePanel.vue";

type ToastType = "success" | "error" | "info";
const emit = defineEmits<{ toast: [type: ToastType, message: string] }>();

const activePill = useLocalStorage<string>(
  "lifelogr-data-backup-pill",
  "storage",
);
const pills = [
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "import-export", label: "Import / Export", icon: FileUp },
  { id: "backups", label: "Backups", icon: Cloud },
  { id: "maintenance", label: "Maintenance", icon: Wrench },
] as const;

function forward(type: ToastType, message: string) {
  emit("toast", type, message);
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- Pill sub-nav -->
    <div
      class="flex items-center gap-1 p-0.5 bg-surface border border-border rounded-md w-fit"
    >
      <button
        v-for="pill in pills"
        :key="pill.id"
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
    <StoragePanel v-if="activePill === 'storage'" @toast="forward" />
    <ImportExportPanel
      v-else-if="activePill === 'import-export'"
      @toast="forward"
    />
    <BackupTab v-else-if="activePill === 'backups'" @toast="forward" />
    <MaintenancePanel
      v-else-if="activePill === 'maintenance'"
      @toast="forward"
    />
  </div>
</template>
