<script setup lang="ts">
import { ref, computed } from "vue";
import { entriesApi } from "../../../api/entries";
import {
  exportHtml,
  getExportPdfUrl,
  exportDiarium,
  getExportDiariumDbUrl,
} from "../../../api/export";
import { useEntriesStore } from "../../../stores/entries";
import { saveFile, pickFile } from "../../../utils/fileDialog";
import {
  Download,
  Upload,
  Loader,
  FileUp,
  FileDown,
  FileJson,
  FileSpreadsheet,
  Database,
  ChevronDown,
} from "lucide-vue-next";
import SettingsSection from "../shared/SettingsSection.vue";
import SButton from "../shared/SButton.vue";

const emit = defineEmits<{
  toast: [type: "success" | "error" | "info", message: string];
}>();
function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const entriesStore = useEntriesStore();

// ── Import ──
const importing = ref(false);
const importMenuOpen = ref(false);

async function runImport(accept: string) {
  importMenuOpen.value = false;
  const file = await pickFile({ accept });
  if (!file) return;
  importing.value = true;
  try {
    const r = await entriesApi.importFile(file);
    entriesStore.refreshAll();
    emit(
      "toast",
      "success",
      `Imported ${r.imported} entries${r.skipped ? ` (${r.skipped} skipped)` : ""}`,
    );
  } catch (e: unknown) {
    emit("toast", "error", `Import failed: ${errMsg(e)}`);
  } finally {
    importing.value = false;
  }
}

// ── Export ──
const exportRange = ref<"all" | "range">("all");
const exportFrom = ref("");
const exportTo = ref("");
const exportMenuOpen = ref(false);
const exportingHtml = ref(false);
const exportingDiarium = ref(false);
const exportingDiariumDb = ref(false);

const rangeError = computed(() => {
  if (exportRange.value !== "range") return "";
  if (!exportFrom.value || !exportTo.value) return "";
  return exportFrom.value > exportTo.value
    ? "Start date must be before end date"
    : "";
});
const exportDisabled = computed(
  () =>
    !!rangeError.value ||
    (exportRange.value === "range" && (!exportFrom.value || !exportTo.value)),
);
const rangeStart = computed(() =>
  exportRange.value === "range" ? exportFrom.value || undefined : undefined,
);
const rangeEnd = computed(() =>
  exportRange.value === "range" ? exportTo.value || undefined : undefined,
);

async function downloadMarkdown() {
  exportMenuOpen.value = false;
  const resp = await fetch(
    entriesApi.exportMarkdownUrl(rangeStart.value, rangeEnd.value),
  );
  const blob = await resp.blob();
  await saveFile({
    data: blob,
    defaultName: "lifelogr-export.zip",
    filters: [{ name: "ZIP", extensions: ["zip"] }],
  });
  emit("toast", "success", "ZIP export saved");
}
async function downloadJsonExport() {
  exportMenuOpen.value = false;
  const resp = await fetch(
    entriesApi.exportJsonUrl(rangeStart.value, rangeEnd.value),
  );
  const blob = await resp.blob();
  await saveFile({
    data: blob,
    defaultName: "lifelogr-export.json",
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  emit("toast", "success", "JSON export saved");
}
async function downloadHtmlExport() {
  exportMenuOpen.value = false;
  exportingHtml.value = true;
  try {
    const html = await exportHtml(rangeStart.value, rangeEnd.value);
    const blob = new Blob([html], { type: "text/html" });
    await saveFile({
      data: blob,
      defaultName: "lifelogr-export.html",
      filters: [{ name: "HTML", extensions: ["html"] }],
    });
    emit("toast", "success", "HTML export saved");
  } catch (e: unknown) {
    emit("toast", "error", `HTML export failed: ${errMsg(e)}`);
  } finally {
    exportingHtml.value = false;
  }
}
async function downloadPdfExport() {
  exportMenuOpen.value = false;
  const url = getExportPdfUrl(rangeStart.value, rangeEnd.value);
  const resp = await fetch(url);
  const blob = await resp.blob();
  await saveFile({
    data: blob,
    defaultName: "lifelogr-export.pdf",
    filters: [{ name: "PDF", extensions: ["pdf"] }],
  });
}
async function downloadDiarium() {
  exportMenuOpen.value = false;
  exportingDiarium.value = true;
  try {
    const json = await exportDiarium(rangeStart.value, rangeEnd.value);
    const blob = new Blob([json], { type: "application/json" });
    await saveFile({
      data: blob,
      defaultName: "lifelogr-export.json",
      filters: [{ name: "JSON", extensions: ["json"] }],
    });
    emit("toast", "success", "Diarium JSON export saved");
  } catch (e: unknown) {
    emit("toast", "error", `Diarium export failed: ${errMsg(e)}`);
  } finally {
    exportingDiarium.value = false;
  }
}
async function downloadDiariumDb() {
  exportMenuOpen.value = false;
  exportingDiariumDb.value = true;
  try {
    const url = getExportDiariumDbUrl(rangeStart.value, rangeEnd.value);
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    await saveFile({
      data: blob,
      defaultName: "lifelogr-export.diary",
      filters: [{ name: "Diarium", extensions: ["diary"] }],
    });
    emit("toast", "success", ".diary export saved");
  } catch (e: unknown) {
    emit("toast", "error", `.diary export failed: ${errMsg(e)}`);
  } finally {
    exportingDiariumDb.value = false;
  }
}
</script>

<template>
  <SettingsSection
    title="Import / Export"
    :icon="FileUp"
    description="Bring entries in or export your journal"
    setting-key="Export"
    card-class="divide-y divide-border"
  >
    <!-- Import -->
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

    <!-- Export -->
    <div class="p-3 space-y-2">
      <div class="flex items-center gap-2.5 flex-wrap">
        <Download
          :size="13"
          class="text-text-muted shrink-0"
          aria-hidden="true"
        />
        <span class="text-[13px] text-text-secondary">Export</span>
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
      <p v-if="rangeError" class="text-[11px] text-danger pl-[25px]">
        {{ rangeError }}
      </p>

      <div class="relative pl-[25px]">
        <SButton
          variant="primary"
          :disabled="exportDisabled"
          @click="exportMenuOpen = !exportMenuOpen"
        >
          <Download :size="12" /> Export as… <ChevronDown :size="11" />
        </SButton>
        <div
          v-if="exportMenuOpen"
          class="absolute z-20 mt-1 w-44 rounded-md border border-border bg-surface shadow-lg overflow-hidden"
        >
          <button class="export-item" @click="downloadJsonExport">
            <FileJson :size="12" /> JSON
          </button>
          <button class="export-item" @click="downloadMarkdown">
            <FileUp :size="12" /> Markdown ZIP
          </button>
          <button
            class="export-item"
            :disabled="exportingHtml"
            @click="downloadHtmlExport"
          >
            <Loader
              v-if="exportingHtml"
              :size="12"
              class="animate-spin"
            /><Download v-else :size="12" /> HTML
          </button>
          <button class="export-item" @click="downloadPdfExport">
            <Download :size="12" /> PDF
          </button>
          <button
            class="export-item"
            :disabled="exportingDiarium"
            @click="downloadDiarium"
          >
            <Loader
              v-if="exportingDiarium"
              :size="12"
              class="animate-spin"
            /><Download v-else :size="12" /> Diarium JSON
          </button>
          <button
            class="export-item"
            :disabled="exportingDiariumDb"
            @click="downloadDiariumDb"
          >
            <Loader
              v-if="exportingDiariumDb"
              :size="12"
              class="animate-spin"
            /><Database v-else :size="12" /> Diarium .diary
          </button>
        </div>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.import-item,
.export-item {
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
.import-item:hover,
.export-item:hover {
  background-color: var(--color-surface-hover, rgba(255, 255, 255, 0.05));
}
</style>
