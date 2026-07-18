<script setup lang="ts">
import { ref } from "vue";
import { errMsg } from '../../../utils/error'
import { entriesApi } from "../../../api/entries";
import { vacuumDatabase, checkIntegrity } from "../../../api/settings";
import { Database, Copy, Wrench, Shield, Loader } from "lucide-vue-next";
import SettingsSection from "../shared/SettingsSection.vue";
import SettingRow from "../shared/SettingRow.vue";
import SButton from "../shared/SButton.vue";

const emit = defineEmits<{
  toast: [type: "success" | "error" | "info", message: string];
}>();

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

const deduplicating = ref(false);
const vacuuming = ref(false);
const checkingIntegrity = ref(false);

async function handleDeduplicate() {
  deduplicating.value = true;
  try {
    const r = await entriesApi.deduplicate();
    if (r.duplicates_removed === 0)
      emit("toast", "info", "No duplicates found");
    else
      emit(
        "toast",
        "success",
        `Removed ${r.duplicates_removed} duplicate${r.duplicates_removed > 1 ? "s" : ""} across ${r.groups_found} group${r.groups_found > 1 ? "s" : ""}`,
      );
  } catch (e: unknown) {
    emit("toast", "error", `Deduplicate failed: ${errMsg(e)}`);
  } finally {
    deduplicating.value = false;
  }
}
async function handleVacuum() {
  vacuuming.value = true;
  try {
    const r = await vacuumDatabase();
    emit(
      "toast",
      "success",
      `Database compacted — ${formatBytes(r.reclaimed_bytes)} reclaimed`,
    );
  } catch (e: unknown) {
    emit("toast", "error", `Vacuum failed: ${errMsg(e)}`);
  } finally {
    vacuuming.value = false;
  }
}
async function handleIntegrityCheck() {
  checkingIntegrity.value = true;
  try {
    const r = await checkIntegrity();
    if (r.status === "ok") emit("toast", "success", "Database integrity: OK");
    else emit("toast", "error", `Integrity check failed: ${r.message}`);
  } catch (e: unknown) {
    emit("toast", "error", `Check failed: ${errMsg(e)}`);
  } finally {
    checkingIntegrity.value = false;
  }
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
          {{ deduplicating ? "Scanning…" : "Deduplicate" }}
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
          {{ vacuuming ? "Compacting…" : "Vacuum" }}
        </SButton>
      </SettingRow>
    </div>
    <div class="p-3">
      <SettingRow
        :icon="Shield"
        label="Check integrity"
        description="Verifies the SQLite database file is not corrupt."
      >
        <SButton
          variant="ghost"
          :disabled="checkingIntegrity"
          @click="handleIntegrityCheck"
        >
          <Loader v-if="checkingIntegrity" :size="12" class="animate-spin" />
          {{ checkingIntegrity ? "Checking…" : "Check" }}
        </SButton>
      </SettingRow>
    </div>
  </SettingsSection>
</template>
