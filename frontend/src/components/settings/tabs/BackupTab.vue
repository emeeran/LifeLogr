<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useBackupStore } from "../../../stores/backup";
import { backupApi } from "../../../api/backup";
import { useEntriesStore } from "../../../stores/entries";
import { useSyncStore } from "../../../stores/sync";
import { isTauri } from "../../../api/client";
import { saveFile, pickFile, pickFolder } from "../../../utils/fileDialog";
import { useLocalStorage } from "@vueuse/core";
import { providerLabel } from "../../../utils/settings";
import {
  Cloud,
  RefreshCw,
  RotateCcw,
  Plus,
  Trash2,
  Download,
  AlertTriangle,
  CheckCircle2,
  Loader,
  HardDrive,
  FolderOpen,
  Database,
} from "lucide-vue-next";
import ConfirmDialog from "../../common/ConfirmDialog.vue";
import SettingsSection from "../shared/SettingsSection.vue";
import SettingRow from "../shared/SettingRow.vue";
import ToggleSwitch from "../shared/ToggleSwitch.vue";
import SButton from "../shared/SButton.vue";
import SettingGroup from "../shared/SettingGroup.vue";

const emit = defineEmits<{
  toast: [type: "success" | "error" | "info", message: string];
}>();

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const backup = useBackupStore();
const entriesStore = useEntriesStore();
const syncStore = useSyncStore();

// ── Local archive ──
const importing = ref(false);

async function handleBackupDownload() {
  const resp = await fetch(backupApi.exportLocal());
  const blob = await resp.blob();
  const defaultName = `lifelogr-backup-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.tar.gz`;
  const saved = await saveFile({
    data: blob,
    defaultName,
    filters: [{ name: "Tar Archive", extensions: ["tar.gz"] }],
  });
  if (saved) emit("toast", "success", "Backup saved");
}

async function handleBackupRestore() {
  const file = await pickFile({ accept: ".tar.gz,.tgz" });
  if (!file) return;
  importing.value = true;
  try {
    const r = await backupApi.importLocal(file);
    entriesStore.refreshAll();
    emit("toast", "success", `Restored — ${r.restored.join(", ")}`);
  } catch (e: unknown) {
    emit("toast", "error", `Import failed: ${errMsg(e)}`);
  } finally {
    importing.value = false;
  }
}

// ── Cloud Backup ──
const showCreate = ref(false);
const newProvider = ref("webdav");
const newCredentials = ref<Record<string, string>>({});
const newSchedule = ref("");
const newFreqType = ref<"daily" | "weekly" | "monthly">("daily");
const newTime = ref("03:00");
const newLabel = ref("");
const testResult = ref<{
  configId: number;
  success: boolean;
  message: string;
} | null>(null);
const backingUp = ref<number | null>(null);
const restoring = ref<number | null>(null);
const deleteConfirm = ref<number | null>(null);
const restoreConfirm = ref<{ configId: number; provider: string } | null>(null);

const providerFields: Record<string, { label: string; placeholder: string }[]> =
  {
    webdav: [
      {
        label: "URL",
        placeholder: "https://dav.example.com/remote.php/dav/files/",
      },
      { label: "Username", placeholder: "user" },
      { label: "Password", placeholder: "password or app token" },
    ],
    google_drive: [
      { label: "Client ID", placeholder: "xxxx.apps.googleusercontent.com" },
      { label: "Client Secret", placeholder: "GOCSPX-xxxx" },
      { label: "Refresh Token", placeholder: "1//xxxx" },
    ],
    box: [
      { label: "Client ID", placeholder: "your Box client ID" },
      { label: "Client Secret", placeholder: "your Box client secret" },
      { label: "Refresh Token", placeholder: 'set via "Sign in with Box"' },
    ],
    onedrive: [
      { label: "Client ID", placeholder: "xxxx-xxxx-xxxx" },
      { label: "Client Secret", placeholder: "xxxx~xxxx" },
      { label: "Refresh Token", placeholder: "0.ARoxxxx" },
    ],
    dropbox: [{ label: "Access Token", placeholder: "sl.xxxxx" }],
    synology: [
      { label: "URL", placeholder: "https://nas.local:5006/path" },
      { label: "Username", placeholder: "admin" },
      { label: "Password", placeholder: "app password" },
    ],
  };
const currentFields = computed(() => providerFields[newProvider.value] ?? []);

function resetNewCredentials() {
  const creds: Record<string, string> = {};
  for (const f of currentFields.value)
    creds[f.label.toLowerCase().replace(/\s+/g, "_")] = "";
  newCredentials.value = creds;
}

const showManualGoogleFields = ref(false);

async function startGoogleDriveAuth() {
  try {
    const res = await backupApi.getGoogleDriveAuthUrl();
    window.open(res.auth_url, "_blank");
    emit("toast", "info", "Opening Google Authentication in browser...");
    showCreate.value = false;
    setTimeout(async () => {
      await backup.fetchConfigs();
    }, 6000);
  } catch (e: unknown) {
    emit("toast", "error", `Google auth initiation failed: ${errMsg(e)}`);
  }
}

async function startBoxAuth() {
  try {
    const res = await backupApi.getBoxAuthUrl();
    window.open(res.auth_url, "_blank");
    emit("toast", "info", "Opening Box Authentication in browser...");
    showCreate.value = false;
    setTimeout(async () => {
      await backup.fetchConfigs();
    }, 6000);
  } catch (e: unknown) {
    emit("toast", "error", `Box auth initiation failed: ${errMsg(e)}`);
  }
}

function openCreateForm() {
  newProvider.value = "webdav";
  showManualGoogleFields.value = false;
  resetNewCredentials();
  newSchedule.value = "";
  newFreqType.value = "daily";
  newTime.value = "03:00";
  newLabel.value = "";
  showCreate.value = true;
}

function timeToCron(time: string, freq: string): string {
  const [h, m] = time.split(":").map(Number);
  const hh = isNaN(h) ? 3 : h;
  const mm = isNaN(m) ? 0 : m;
  if (freq === "weekly") return `${mm} ${hh} * * 0`;
  if (freq === "monthly") return `${mm} ${hh} 1 * *`;
  return `${mm} ${hh} * * *`;
}

async function createConfig() {
  const filtered: Record<string, string> = {};
  for (const [k, v] of Object.entries(newCredentials.value))
    if (v.trim()) filtered[k] = v;
  // Synology NAS is a WebDAV preset — store as webdav so the existing provider handles it.
  const provider =
    newProvider.value === "synology" ? "webdav" : newProvider.value;
  const label =
    newLabel.value.trim() ||
    (newProvider.value === "synology" ? "Synology NAS" : undefined);
  await backupApi.createConfig({
    provider,
    label,
    credentials: filtered,
    schedule_cron: timeToCron(newTime.value, newFreqType.value),
  });
  showCreate.value = false;
  await backup.fetchConfigs();
  emit("toast", "success", `${providerLabel(newProvider.value)} added`);
}

async function testConn(id: number) {
  testResult.value = null;
  try {
    testResult.value = {
      configId: id,
      ...(await backupApi.testConnection(id)),
    };
  } catch (e: unknown) {
    testResult.value = { configId: id, success: false, message: errMsg(e) };
  }
}

async function runBackup(configId: number) {
  backingUp.value = configId;
  testResult.value = null;
  try {
    const snap = await backup.runBackup(configId);
    emit(
      "toast",
      snap.status === "completed" ? "success" : "error",
      snap.status === "completed"
        ? `Backup done — ${snap.entries_synced}e ${snap.media_synced}m`
        : `Backup failed: ${snap.error_message ?? "unknown"}`,
    );
    await backup.fetchSnapshots();
  } catch (e: unknown) {
    emit("toast", "error", `Backup failed: ${errMsg(e)}`);
  } finally {
    backingUp.value = null;
  }
}

async function confirmRestore() {
  if (!restoreConfirm.value) return;
  const { configId, provider } = restoreConfirm.value;
  restoreConfirm.value = null;
  restoring.value = configId;
  try {
    const r = await backup.restore(configId);
    emit(
      "toast",
      "success",
      `Restored from ${providerLabel(provider)} — ${(r as any).entries_restored ?? 0}e ${(r as any).media_restored ?? 0}m`,
    );
  } catch (e: unknown) {
    emit("toast", "error", `Restore failed: ${errMsg(e)}`);
  } finally {
    restoring.value = null;
  }
}

async function confirmDelete() {
  if (!deleteConfirm.value) return;
  try {
    await backup.deleteConfig(deleteConfirm.value);
    emit("toast", "info", "Config deleted");
  } catch (e: unknown) {
    emit("toast", "error", `Delete failed: ${errMsg(e)}`);
  } finally {
    deleteConfirm.value = null;
  }
}

// ── Sync ──
const syncPushing = ref(false);
const syncPulling = ref(false);
const flushConfirm = ref(false);

async function handleSyncPush() {
  syncPushing.value = true;
  try {
    await syncStore.push("local_file");
    emit("toast", "success", "Push done");
  } catch (e: unknown) {
    emit("toast", "error", `Push failed: ${errMsg(e)}`);
  } finally {
    syncPushing.value = false;
  }
}
async function handleSyncPull() {
  syncPulling.value = true;
  try {
    await syncStore.pull("local_file");
    emit("toast", "success", "Pull done");
  } catch (e: unknown) {
    emit("toast", "error", `Pull failed: ${errMsg(e)}`);
  } finally {
    syncPulling.value = false;
  }
}
async function handleSyncFlush() {
  try {
    await syncStore.flush();
    emit("toast", "success", "Queue flushed");
    syncStore.fetchStatus();
  } catch (e: unknown) {
    emit("toast", "error", `Flush failed: ${errMsg(e)}`);
  } finally {
    flushConfirm.value = false;
  }
}

// ── Auto Backup ──
const autoBackupEnabled = useLocalStorage<boolean>(
  "lifelogr-auto-backup-enabled",
  false,
);
const autoBackupPath = useLocalStorage<string>(
  "lifelogr-auto-backup-path",
  "~/Backups/lifelogr",
);
const autoBackupFrequency = useLocalStorage<string>(
  "lifelogr-auto-backup-freq",
  "0 2 * * *",
);
const autoBackupRetention = useLocalStorage<number>(
  "lifelogr-auto-backup-retention",
  10,
);
const autoBackupConfigId = useLocalStorage<number | null>(
  "lifelogr-auto-backup-config-id",
  null,
);

const autoBackupTime = computed({
  get: () => {
    const parts = autoBackupFrequency.value.split(" ");
    if (parts.length >= 2)
      return `${parts[1].padStart(2, "0")}:${parts[0].padStart(2, "0")}`;
    return "02:00";
  },
  set: (val: string) => {
    autoBackupFrequency.value = timeToCron(val, autoBackupFreqType.value);
  },
});
const autoBackupFreqType = computed({
  get: (): string => {
    const p = autoBackupFrequency.value.split(" ");
    if (p.length >= 5) {
      if (p[4] !== "*") return "weekly";
      if (p[2] !== "*") return "monthly";
    }
    return "daily";
  },
  set: (val: string) => {
    autoBackupFrequency.value = timeToCron(autoBackupTime.value, val);
  },
});

const autoBackupHumanPreview = computed(() => {
  const time = autoBackupTime.value;
  const [h, m] = time.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const displayH = h === 0 ? 12 : h > 12 ? h - 12 : h;
  const timeStr = `${displayH}:${String(m).padStart(2, "0")} ${ampm}`;
  const freq = autoBackupFreqType.value;
  if (freq === "weekly") return `Runs weekly on Sunday at ${timeStr}`;
  if (freq === "monthly") return `Runs monthly on the 1st at ${timeStr}`;
  return `Runs daily at ${timeStr}`;
});
const autoBackupStatus = ref<{
  running: boolean;
  backup_scheduled: boolean;
  next_run: string | null;
} | null>(null);
const autoBackupSaving = ref(false);

async function toggleAutoBackup() {
  if (!autoBackupEnabled.value) {
    try {
      const { request } = await import("../../../api/client");
      await request("/backup/schedule", { method: "DELETE" });
      autoBackupStatus.value = {
        running: false,
        backup_scheduled: false,
        next_run: null,
      };
    } catch {
      /* ignore */
    }
  }
}

async function saveAutoBackup() {
  autoBackupSaving.value = true;
  try {
    await backupApi.scheduleBackup(autoBackupFrequency.value, {
      configId: autoBackupConfigId.value ?? undefined,
      backupPath: autoBackupConfigId.value ? undefined : autoBackupPath.value,
      retention: autoBackupConfigId.value
        ? undefined
        : autoBackupRetention.value,
    });
    await loadAutoBackupStatus();
    autoBackupEnabled.value = true;
    emit("toast", "success", "Backup schedule saved");
  } catch (e: any) {
    emit("toast", "error", `Failed to save schedule: ${errMsg(e)}`);
  } finally {
    autoBackupSaving.value = false;
  }
}

async function runBackupNow() {
  try {
    // Cloud destination selected → run that config directly via the per-config
    // /backup/run path. A one-off run needs no persisted schedule, so "Run now"
    // works immediately after linking a provider instead of 404'ing.
    if (autoBackupConfigId.value) {
      const snap = await backup.runBackup(autoBackupConfigId.value);
      emit(
        "toast",
        snap.status === "completed" ? "success" : "error",
        snap.status === "completed"
          ? "Cloud backup completed"
          : `Backup failed: ${snap.error_message ?? "unknown"}`,
      );
      backup.fetchSnapshots();
      return;
    }
    // Local mode: back up to the configured folder now (no saved schedule
    // needed — /run-now accepts the path directly).
    const { request } = await import("../../../api/client");
    const r = await request<{
      mode: string;
      path?: string;
      status?: string;
      error?: string;
    }>(
      `/backup/run-now?backup_path=${encodeURIComponent(autoBackupPath.value)}&retention=${autoBackupRetention.value}`,
      { method: "POST" },
    );
    emit("toast", "success", `Backup saved to ${r.path}`);
    backup.fetchSnapshots();
  } catch (e: unknown) {
    emit("toast", "error", `Backup failed: ${errMsg(e)}`);
  }
}

async function loadAutoBackupStatus() {
  try {
    const { request } = await import("../../../api/client");
    autoBackupStatus.value = await request("/backup/schedule/status");
  } catch {
    /* ignore */
  }
}

async function browseBackupFolder() {
  const folder = await pickFolder();
  if (folder) autoBackupPath.value = folder;
}

onMounted(() => {
  backup.fetchConfigs();
  backup.fetchSnapshots();
  syncStore.fetchStatus();
  loadAutoBackupStatus();
});
</script>

<template>
  <!-- Local archive -->
  <SettingsSection
    title="Local Backup"
    :icon="HardDrive"
    description="Manual archive of your database and media"
    setting-key="Local backup"
  >
    <SettingRow
      :icon="Database"
      label="Local archive"
      description="Download a .tar.gz of your database and media, or restore one."
    >
      <SButton variant="ghost" :icon="Download" @click="handleBackupDownload"
        >Backup</SButton
      >
      <SButton
        variant="ghost"
        :disabled="importing"
        @click="handleBackupRestore"
      >
        <Loader v-if="importing" :size="12" class="animate-spin" /> Restore
      </SButton>
    </SettingRow>
  </SettingsSection>

  <!-- Auto backup -->
  <SettingsSection
    title="Scheduled Backup"
    :icon="RefreshCw"
    description="Automatic local or cloud backups on a schedule"
    setting-key="Scheduled backup"
    card-class="p-3 space-y-2"
  >
    <div class="flex items-center gap-2.5">
      <ToggleSwitch
        v-model="autoBackupEnabled"
        @update:model-value="toggleAutoBackup"
      />
      <span class="text-[13px] text-text-secondary flex-1">Auto backup</span>
      <span
        v-if="autoBackupStatus?.backup_scheduled"
        class="text-[10px] text-green-400 font-medium flex items-center gap-1"
      >
        <CheckCircle2 :size="11" /> Scheduled
      </span>
    </div>
    <div v-if="autoBackupEnabled" class="space-y-1.5 pl-7">
      <SettingRow label="Destination">
        <select v-model="autoBackupConfigId" class="settings-select flex-1">
          <option :value="null">Local folder</option>
          <option v-for="c in backup.configs" :key="c.id" :value="c.id">
            {{ providerLabel(c.provider) }}
          </option>
        </select>
      </SettingRow>
      <template v-if="!autoBackupConfigId">
        <SettingRow label="Folder">
          <input
            v-model="autoBackupPath"
            placeholder="~/Backups/lifelogr"
            class="settings-input flex-1"
          />
          <SButton
            v-if="isTauri"
            variant="ghost"
            size="xs"
            :icon="FolderOpen"
            @click="browseBackupFolder"
            >Browse</SButton
          >
        </SettingRow>
        <SettingRow label="Keep">
          <input
            v-model.number="autoBackupRetention"
            type="number"
            min="1"
            max="100"
            class="settings-input w-16"
          />
          <span class="text-[11px] text-text-muted">backups</span>
        </SettingRow>
      </template>
      <SettingRow label="Time">
        <input v-model="autoBackupTime" type="time" class="settings-input" />
      </SettingRow>
      <SettingRow label="Frequency">
        <select v-model="autoBackupFreqType" class="settings-select">
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
      </SettingRow>
      <p class="text-[11px] text-accent/80">{{ autoBackupHumanPreview }}</p>
      <div class="flex items-center gap-1.5 pt-1">
        <SButton
          variant="primary"
          :disabled="autoBackupSaving"
          @click="saveAutoBackup"
        >
          <Loader v-if="autoBackupSaving" :size="12" class="animate-spin" />
          Save Schedule
        </SButton>
        <SButton variant="ghost" @click="runBackupNow">Run now</SButton>
      </div>
    </div>
  </SettingsSection>

  <!-- Cloud -->
  <SettingsSection
    title="Cloud Backup"
    :icon="Cloud"
    description="Sync your journal to cloud storage"
    setting-key="Cloud backup"
  >
    <template #actions>
      <SButton variant="primary" size="xs" :icon="Plus" @click="openCreateForm"
        >Add</SButton
      >
    </template>

    <!-- Create form -->
    <div
      v-if="showCreate"
      class="mb-3 p-3 border border-accent/30 rounded-md space-y-2"
    >
      <SettingGroup label="Provider">
        <select
          v-model="newProvider"
          class="settings-select"
          @change="resetNewCredentials"
        >
          <option value="webdav">WebDAV</option>
          <option value="google_drive">Google Drive</option>
          <option value="box">Box</option>
          <option value="onedrive">OneDrive</option>
          <option value="dropbox">Dropbox</option>
          <option value="synology">Synology NAS</option>
        </select>
      </SettingGroup>
      <SettingRow label="Name">
        <input
          v-model="newLabel"
          class="settings-input flex-1"
          placeholder="Optional display name (e.g. Synology NAS)"
        />
      </SettingRow>
      <div
        v-if="newProvider === 'google_drive'"
        class="flex flex-col gap-1.5 py-1"
      >
        <SButton variant="primary" @click="startGoogleDriveAuth"
          >Sign in with Google</SButton
        >
        <div class="text-center">
          <a
            href="#"
            @click.prevent="showManualGoogleFields = !showManualGoogleFields"
            class="text-[10px] text-text-muted hover:text-accent underline"
          >
            {{
              showManualGoogleFields
                ? "Hide manual settings"
                : "Or configure manually (Advanced)"
            }}
          </a>
        </div>
      </div>
      <div v-else-if="newProvider === 'box'" class="flex flex-col gap-1.5 py-1">
        <SButton variant="primary" @click="startBoxAuth"
          >Sign in with Box</SButton
        >
        <p class="text-[10px] text-text-muted text-center">
          Authorise in your browser, or fill the fields below manually.
        </p>
      </div>
      <template v-if="newProvider !== 'google_drive' || showManualGoogleFields">
        <SettingRow
          v-for="field in currentFields"
          :key="field.label"
          :label="field.label"
        >
          <input
            v-model="
              newCredentials[field.label.toLowerCase().replace(/\s+/g, '_')]
            "
            class="settings-input flex-1"
            :placeholder="field.placeholder"
          />
        </SettingRow>
      </template>
      <SettingRow label="Time">
        <input v-model="newTime" type="time" class="settings-input" />
      </SettingRow>
      <SettingRow label="Frequency">
        <select v-model="newFreqType" class="settings-select">
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
      </SettingRow>
      <div class="flex gap-1.5">
        <SButton variant="primary" @click="createConfig">Save</SButton>
        <SButton variant="ghost" @click="showCreate = false">Cancel</SButton>
      </div>
    </div>

    <!-- Configs -->
    <div
      v-for="config in backup.configs"
      :key="config.id"
      class="p-2.5 mb-1 last:mb-0 rounded-md border border-border"
    >
      <div class="flex items-center gap-2 mb-1.5">
        <span class="text-[12px] font-medium text-text-primary">{{
          config.label || providerLabel(config.provider)
        }}</span>
        <span v-if="config.last_sync_at" class="text-[10px] text-text-muted">{{
          new Date(config.last_sync_at).toLocaleDateString()
        }}</span>
        <SButton
          variant="ghost"
          size="xs"
          :icon="Trash2"
          title="Delete config"
          class="ml-auto !text-text-muted hover:!text-danger"
          @click="deleteConfirm = config.id"
        />
      </div>
      <div class="flex items-center gap-1.5">
        <SButton variant="ghost" size="xs" @click="testConn(config.id)"
          >Test</SButton
        >
        <SButton
          variant="accent-soft"
          size="xs"
          :disabled="backingUp === config.id"
          @click="runBackup(config.id)"
        >
          <Loader
            v-if="backingUp === config.id"
            :size="11"
            class="animate-spin"
          />{{ backingUp === config.id ? "…" : "Backup" }}
        </SButton>
        <SButton
          variant="danger-soft"
          size="xs"
          :disabled="restoring === config.id"
          @click="
            restoreConfirm = { configId: config.id, provider: config.provider }
          "
        >
          <RotateCcw
            v-if="restoring === config.id"
            :size="11"
            class="animate-spin"
          />{{ restoring === config.id ? "…" : "Restore" }}
        </SButton>
      </div>
      <div
        v-if="testResult?.configId === config.id"
        class="mt-1 flex items-center gap-1 text-[11px]"
        :class="testResult.success ? 'text-green-400' : 'text-red-400'"
      >
        <CheckCircle2 v-if="testResult.success" :size="11" /><AlertTriangle
          v-else
          :size="11"
        />
        {{ testResult.message }}
      </div>
    </div>

    <div v-if="!backup.configs.length && !showCreate" class="text-center py-4">
      <Cloud :size="20" class="mx-auto text-text-muted mb-1.5" />
      <p class="text-[11px] text-text-secondary">
        No cloud backups configured.
      </p>
      <p class="text-[10px] text-text-muted mt-0.5">
        Click Add to connect a cloud provider.
      </p>
    </div>

    <details
      v-if="backup.snapshots.length"
      class="mt-2 border-t border-border pt-2"
    >
      <summary
        class="text-[11px] text-text-muted cursor-pointer hover:text-text-primary transition-colors"
      >
        {{ backup.snapshots.length }} backups
      </summary>
      <div class="mt-1 space-y-0.5">
        <div
          v-for="snap in backup.snapshots.slice(0, 10)"
          :key="snap.id"
          class="px-2 py-0.5 rounded text-[11px]"
        >
          <div class="flex items-center gap-2">
            <CheckCircle2
              v-if="snap.status === 'completed'"
              :size="10"
              class="text-green-400"
            />
            <AlertTriangle v-else :size="10" class="text-red-400" />
            <span class="text-text-muted"
              >{{ snap.entries_synced }}e {{ snap.media_synced }}m</span
            >
            <span class="ml-auto text-text-muted">{{
              new Date(snap.started_at).toLocaleDateString()
            }}</span>
          </div>
          <div
            v-if="snap.status !== 'completed' && snap.error_message"
            class="ml-3.5 text-red-400/80 text-[10px] truncate"
            :title="snap.error_message"
          >
            {{ snap.error_message }}
          </div>
        </div>
      </div>
    </details>
  </SettingsSection>

  <!-- Sync -->
  <SettingsSection
    title="Sync Queue"
    :icon="RefreshCw"
    description="Manage pending synchronization operations"
    setting-key="Sync queue"
  >
    <div
      v-if="syncStore.status"
      class="flex items-center gap-3 text-[11px] mb-2"
    >
      <span
        :class="
          syncStore.status.status === 'ok' ? 'text-green-400' : 'text-accent'
        "
        class="font-medium"
        >{{ syncStore.status.status }}</span
      >
      <span class="text-text-muted"
        >{{ syncStore.status.pending_count }} pending</span
      >
      <span class="text-text-muted ml-auto">{{
        syncStore.status.last_sync_at
          ? new Date(syncStore.status.last_sync_at).toLocaleDateString()
          : "—"
      }}</span>
    </div>
    <div class="flex items-center gap-1.5">
      <SButton
        variant="accent-soft"
        :disabled="syncPushing"
        @click="handleSyncPush"
      >
        <Loader v-if="syncPushing" :size="11" class="animate-spin" />Push
      </SButton>
      <SButton variant="ghost" :disabled="syncPulling" @click="handleSyncPull">
        <Loader v-if="syncPulling" :size="11" class="animate-spin" />Pull
      </SButton>
      <SButton variant="danger-soft" :icon="Trash2" @click="flushConfirm = true"
        >Flush</SButton
      >
    </div>
  </SettingsSection>

  <ConfirmDialog
    v-if="restoreConfirm"
    title="Restore from backup?"
    :message="`Replace all local data with backup from ${providerLabel(restoreConfirm.provider)}?`"
    @confirm="confirmRestore"
    @cancel="restoreConfirm = null"
  />
  <ConfirmDialog
    v-if="deleteConfirm"
    title="Delete config?"
    message="Snapshots kept."
    @confirm="confirmDelete"
    @cancel="deleteConfirm = null"
  />
  <ConfirmDialog
    v-if="flushConfirm"
    title="Flush sync queue?"
    message="This permanently discards all pending sync operations. Continue?"
    @confirm="handleSyncFlush"
    @cancel="flushConfirm = false"
  />
</template>
