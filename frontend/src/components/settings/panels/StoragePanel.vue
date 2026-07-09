<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  getSettings,
  getStoragePath,
  updateStoragePath,
} from "../../../api/settings";
import type { AppSettings, StoragePathInfo } from "../../../api/settings";
import { isTauri } from "../../../api/client";
import { pickFolder } from "../../../utils/fileDialog";
import { HardDrive, FolderOpen, Loader, MapPin } from "lucide-vue-next";
import SettingsSection from "../shared/SettingsSection.vue";
import SettingRow from "../shared/SettingRow.vue";
import SkeletonCard from "../shared/SkeletonCard.vue";
import SButton from "../shared/SButton.vue";
import ConfirmDialog from "../../common/ConfirmDialog.vue";

const emit = defineEmits<{
  toast: [type: "success" | "error" | "info", message: string];
}>();
function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const appSettings = ref<AppSettings | null>(null);
const storagePath = ref<StoragePathInfo | null>(null);
const relocating = ref(false);
const editingPath = ref(false);
const pathInput = ref("");
const relocateConfirm = ref(false);

async function load() {
  try {
    appSettings.value = await getSettings();
    storagePath.value = await getStoragePath();
    pathInput.value = storagePath.value.data_dir;
  } catch {
    /* ignore */
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

async function chooseFolder() {
  const folder = await pickFolder();
  if (folder) {
    pathInput.value = folder;
    relocateConfirm.value = true;
  }
}

function submitManual() {
  editingPath.value = false;
  if (pathInput.value && pathInput.value !== storagePath.value?.data_dir) {
    relocateConfirm.value = true;
  }
}

async function confirmRelocate() {
  if (!pathInput.value) {
    relocateConfirm.value = false;
    return;
  }
  relocating.value = true;
  try {
    const r = await updateStoragePath(pathInput.value);
    emit("toast", "success", `Data moved to ${r.new_path}`);
    await load();
  } catch (e: unknown) {
    emit("toast", "error", `Move failed: ${errMsg(e)}`);
  } finally {
    relocating.value = false;
    relocateConfirm.value = false;
  }
}

onMounted(load);
</script>

<template>
  <!-- Storage usage -->
  <SettingsSection
    title="Storage"
    :icon="HardDrive"
    description="Disk usage and entry statistics"
    setting-key="Storage"
  >
    <div v-if="appSettings?.storage" class="grid grid-cols-2 gap-x-6 gap-y-2">
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Database</span>
        <span class="text-text-primary font-medium">{{
          formatBytes(appSettings.storage.db_size_bytes)
        }}</span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Entries</span>
        <span class="text-text-primary font-medium">{{
          appSettings.storage.entry_count
        }}</span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Media files</span>
        <span class="text-text-primary font-medium">
          {{ appSettings.storage.media_count }} ({{
            formatBytes(appSettings.storage.media_size_bytes)
          }})
        </span>
      </div>
      <div class="flex items-center justify-between text-[12px]">
        <span class="text-text-secondary">Total</span>
        <span class="text-text-primary font-semibold">
          {{
            formatBytes(
              appSettings.storage.db_size_bytes +
                appSettings.storage.media_size_bytes,
            )
          }}
        </span>
      </div>
    </div>
    <SkeletonCard v-else :lines="4" />
  </SettingsSection>

  <!-- Storage location -->
  <SettingsSection
    title="Storage Location"
    :icon="MapPin"
    description="Where your database and media live"
    setting-key="Storage location"
    card-class="p-3 space-y-2"
  >
    <SettingRow label="Folder" :description="storagePath?.db_path">
      <span
        class="text-[12px] text-text-secondary truncate max-w-[36ch]"
        :title="storagePath?.data_dir"
      >
        {{ storagePath?.data_dir ?? "—" }}
      </span>
    </SettingRow>
    <SettingRow
      label="Move data"
      description="Hot-move database, media, and keys to a new folder."
    >
      <SButton
        v-if="isTauri"
        variant="ghost"
        :icon="FolderOpen"
        :disabled="relocating"
        @click="chooseFolder"
      >
        <Loader v-if="relocating" :size="12" class="animate-spin" /> Change…
      </SButton>
      <template v-else>
        <input
          v-if="editingPath"
          v-model="pathInput"
          class="settings-input flex-1"
          placeholder="/path/to/folder"
          @keydown.enter="submitManual"
        />
        <SButton
          v-else
          variant="ghost"
          :icon="FolderOpen"
          @click="editingPath = true"
          >Change…</SButton
        >
        <SButton
          v-if="editingPath"
          variant="primary"
          :disabled="relocating"
          @click="submitManual"
        >
          <Loader v-if="relocating" :size="12" class="animate-spin" /> Apply
        </SButton>
      </template>
    </SettingRow>
    <p class="text-[11px] text-text-muted pl-1">
      The current folder is kept intact; restart the app so logs follow the new
      location.
    </p>
  </SettingsSection>

  <ConfirmDialog
    v-if="relocateConfirm"
    title="Move data folder?"
    :message="`Copy database + media to ${pathInput} and switch to it? The current folder is kept intact.`"
    @confirm="confirmRelocate"
    @cancel="relocateConfirm = false"
  />
</template>
