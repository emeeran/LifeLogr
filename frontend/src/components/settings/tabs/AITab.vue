<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import {
  getThemes,
  pullModel,
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  activateProvider,
  testProvider,
  listProviderModels,
  previewProviderModels,
  getProviderPresets,
} from "../../../api/ai";
import type { AIProvider, AIProviderUpdate, ProviderPreset } from "../../../api/ai";
import type { ThemeInsight } from "../../../types";
import {
  getSettings,
  updateSettings,
  getOllamaModels,
} from "../../../api/settings";
import type { AppSettings, AIModelInfo } from "../../../api/settings";
import { request } from "../../../api/client";
import {
  Brain,
  Sparkles,
  Loader,
  Download as DownloadIcon,
  Link,
  Wifi,
  WifiOff,
  Eye,
  RefreshCw,
  AlertTriangle,
} from "lucide-vue-next";
import SettingsSection from "../shared/SettingsSection.vue";
import SettingRow from "../shared/SettingRow.vue";
import ToggleSwitch from "../shared/ToggleSwitch.vue";
import SkeletonCard from "../shared/SkeletonCard.vue";
import AccordionItem from "../shared/AccordionItem.vue";
import SettingGroup from "../shared/SettingGroup.vue";
import SButton from "../shared/SButton.vue";

const emit = defineEmits<{
  toast: [type: "success" | "error" | "info", message: string];
}>();
function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Pull the backend ``detail`` out of the API client's ``"API <code>: <body>"``
 * message, so provider errors surface readably (e.g. Gemini's "API key not
 * valid") instead of as raw ``{"detail": …}`` JSON. Falls back to ``errMsg``. */
function apiErrMsg(e: unknown): string {
  const raw = errMsg(e);
  const m = raw.match(/API \d+:\s*([\s\S]*)$/);
  if (m) {
    try {
      const parsed = JSON.parse(m[1]);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* body wasn't JSON */
    }
  }
  return raw;
}

function formatModelSize(bytes: number): string {
  if (!bytes) return "";
  const gb = bytes / 1024 ** 3;
  return gb >= 1
    ? `${gb.toFixed(1)} GB`
    : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

// Mirrors backend app.services.ollama_service.is_reasoning_model — reasoning /
// "thinking" models emit long <think> chains and stall every editor AI tool on
// CPU-only machines. We warn (but still allow) when one is selected.
const REASONING_MARKERS = [
  "qwen3",
  "deepseek-r1",
  "qwq",
  "gpt-oss",
  "magistral",
  "openthinker",
  "thinker",
  "reasoning",
  "nemotron",
];
function isReasoningModel(name: string): boolean {
  const lowered = (name ?? "").toLowerCase();
  return REASONING_MARKERS.some((m) => lowered.includes(m));
}
const selectedModelIsReasoning = computed(() =>
  isReasoningModel(appSettings.value?.ai.ollama_model ?? ""),
);

// ── AI Configuration ──
const appSettings = ref<AppSettings | null>(null);
const ollamaModels = ref<AIModelInfo[]>([]);
const settingsLoading = ref(false);
const aiSaving = ref(false);

// Dirty-state tracking: show a "Save" affordance only when edits are pending.
const aiDirty = ref(false);

async function loadAppSettings() {
  settingsLoading.value = true;
  try {
    appSettings.value = await getSettings();
  } catch {
    /* ignore */
  } finally {
    settingsLoading.value = false;
    aiDirty.value = false;
  }
}

// Watch for any change to the ai sub-object once loaded.
watch(
  () => appSettings.value?.ai,
  () => {
    if (appSettings.value) aiDirty.value = true;
  },
  { deep: true },
);

async function loadOllamaModels() {
  try {
    ollamaModels.value = await getOllamaModels();
  } catch {
    /* ignore */
  }
}

const modelsRefreshing = ref(false);
async function refreshModels() {
  modelsRefreshing.value = true;
  try {
    ollamaModels.value = await getOllamaModels();
    const n = ollamaModels.value.length;
    emit("toast", "success", `Found ${n} model${n === 1 ? "" : "s"}`);
  } catch (e: unknown) {
    emit("toast", "error", `Refresh failed: ${errMsg(e)}`);
  } finally {
    modelsRefreshing.value = false;
  }
}

async function saveAISettings() {
  if (!appSettings.value) return;
  aiSaving.value = true;
  try {
    await updateSettings({ ai: appSettings.value.ai });
    aiDirty.value = false;
    emit("toast", "success", "AI settings saved");
  } catch (e: unknown) {
    emit("toast", "error", `Save failed: ${errMsg(e)}`);
  } finally {
    aiSaving.value = false;
  }
}

// ── Connection Test ──
const connTesting = ref(false);
const connStatus = ref<{
  ok: boolean;
  model: string;
  modelLoaded: boolean;
  embedAvailable: boolean;
} | null>(null);

async function testConnection() {
  connTesting.value = true;
  connStatus.value = null;
  try {
    const res = await request<{
      ollama_available: boolean;
      model_name: string;
      model_loaded: boolean;
      embed_model_available: boolean;
      error: string | null;
    }>("/ai/status");
    connStatus.value = {
      ok: res.ollama_available,
      model: res.model_name,
      modelLoaded: res.model_loaded,
      embedAvailable: res.embed_model_available,
    };
    if (!res.ollama_available)
      emit(
        "toast",
        "error",
        `Ollama unavailable: ${res.error ?? "connection refused"}`,
      );
    else
      emit(
        "toast",
        "success",
        `Connected — ${res.model_name} ${res.model_loaded ? "(loaded)" : "(not loaded)"}`,
      );
  } catch (e: unknown) {
    connStatus.value = {
      ok: false,
      model: "",
      modelLoaded: false,
      embedAvailable: false,
    };
    emit("toast", "error", `Connection failed: ${errMsg(e)}`);
  } finally {
    connTesting.value = false;
  }
}

// ── Pull AI Model ──
const pullModelName = ref("");
const pulling = ref(false);
const pullStatus = ref("");

async function handlePullModel() {
  if (!pullModelName.value.trim()) return;
  pulling.value = true;
  pullStatus.value = "Pulling...";
  try {
    await pullModel(pullModelName.value.trim());
    pullStatus.value = `Pull started for ${pullModelName.value.trim()}`;
    emit(
      "toast",
      "success",
      `Model pull started: ${pullModelName.value.trim()}`,
    );
  } catch (e: unknown) {
    pullStatus.value = `Failed: ${errMsg(e)}`;
    emit("toast", "error", `Pull failed: ${errMsg(e)}`);
  } finally {
    pulling.value = false;
  }
}

// ── AI Themes & Insights ──
const themesMonths = ref(6);
const themes = ref<ThemeInsight[]>([]);
const themesLoading = ref(false);

async function fetchThemes() {
  themesLoading.value = true;
  try {
    themes.value = (await getThemes(themesMonths.value)).themes;
  } catch (e: unknown) {
    emit("toast", "error", `Themes failed: ${errMsg(e)}`);
  } finally {
    themesLoading.value = false;
  }
}

function resetAIDefaults() {
  if (!appSettings.value) return;
  const ai = appSettings.value.ai;
  ai.ollama_model = "llama3.2:3b";
  ai.ollama_base_url = "http://localhost:11434";
  ai.ollama_embed_model = "nomic-embed-text";
  ai.enable_embeddings = true;
  ai.enable_tag_suggestions = true;
  ai.enable_sentiment = true;
  ai.enable_summarization = true;
  ai.enable_reflection_prompts = true;
  ai.enable_writer_block_helper = true;
  emit("toast", "success", "AI settings reset to defaults");
}

const availableEmbedModels = computed(() => {
  const names = ollamaModels.value.map((m) => m.name);
  const suggestions = ["nomic-embed-text", "mxbai-embed-large", "all-minilm"];
  return [
    ...new Set([
      ...names.filter(
        (n) => n.includes("embed") || n.includes("e5") || n.includes("minilm"),
      ),
      ...suggestions,
    ]),
  ];
});

// Feature toggles with descriptions + whether they need the embedding model.
const featureToggles = computed(
  () =>
    [
      {
        key: "enable_embeddings",
        label: "Embeddings",
        desc: "Generate vector embeddings. Required for semantic search.",
        needsEmbed: true,
      },
      {
        key: "enable_tag_suggestions",
        label: "Tag suggestions",
        desc: "Suggest tags for entries using the chat model.",
        needsEmbed: false,
      },
      {
        key: "enable_sentiment",
        label: "Sentiment analysis",
        desc: "Score the mood of each entry.",
        needsEmbed: false,
      },
      {
        key: "enable_summarization",
        label: "Summarization",
        desc: "Auto-generate entry summaries.",
        needsEmbed: false,
      },
      {
        key: "enable_reflection_prompts",
        label: "Reflection prompts",
        desc: "Offer writing prompts based on past entries.",
        needsEmbed: false,
      },
      {
        key: "enable_writer_block_helper",
        label: "Writer's block helper",
        desc: "Suggest continuations while writing.",
        needsEmbed: false,
      },
    ] as const,
);

// ── AI providers (cloud, OpenAI-compatible) ──
const providers = ref<AIProvider[]>([]);
const presets = ref<ProviderPreset[]>([]);

// Cloud-egress warning: the active provider (if non-Ollama) receives the text of
// any entry/note an AI tool runs on — it leaves the device. Surfaced as a banner
// here and drives the editor "leaves device" badge + the Privacy tab.
const cloudWarningDismissed = ref(false);
const activeCloudProvider = computed(
  () => providers.value.find((p) => p.is_active && p.preset !== "ollama") ?? null,
);
const activeProviderIsCloud = computed(() => activeCloudProvider.value !== null);
const activeCloudProviderName = computed(
  () => activeCloudProvider.value?.name ?? "your cloud provider",
);
const testingId = ref<number | null>(null);

// Shared inline Add/Edit form. `formMode` null = collapsed; "add" = new-provider
// form; "edit" = editing `editingId`. The same field layout serves both.
type ProviderFormMode = "add" | "edit" | null;
const formMode = ref<ProviderFormMode>(null);
const editingId = ref<number | null>(null);
const providerForm = ref({ name: "", preset: "openai", base_url: "", model: "", api_key: "" });
const providerSaving = ref(false);

// Model selector inside the form: ↻ fetches the provider's real model list
// (preview endpoint for add-mode, or the saved-key per-id endpoint for edit-mode).
// "Custom…" drops back to a free-text input for unlisted models.
const formModels = ref<string[]>([]);
const formModelsLoading = ref(false);
const formModelCustom = ref(false);
const formModelOptions = computed(() => {
  const opts = formModels.value.slice();
  // Always include the current model so the select is never blank.
  if (providerForm.value.model && !opts.includes(providerForm.value.model)) {
    opts.unshift(providerForm.value.model);
  }
  return opts;
});

async function loadProviders() {
  try {
    const [ps, list] = await Promise.all([getProviderPresets(), listProviders()]);
    presets.value = ps;
    providers.value = list;
  } catch {
    /* ignore */
  }
}

function resetFormModels() {
  formModels.value = [];
  formModelCustom.value = false;
}

function openAddForm() {
  const p = presets.value.find((x) => x.key === "openai") ?? presets.value[0];
  providerForm.value = {
    name: p?.label ?? "",
    preset: p?.key ?? "openai",
    base_url: p?.base_url ?? "",
    model: p?.model ?? "",
    api_key: "",
  };
  editingId.value = null;
  resetFormModels();
  formMode.value = "add";
}

function openEditForm(p: AIProvider) {
  providerForm.value = {
    name: p.name,
    preset: p.preset,
    base_url: p.base_url,
    model: p.model,
    api_key: "", // never prefill — the key is write-only
  };
  editingId.value = p.id;
  resetFormModels();
  formMode.value = "edit";
}

function closeForm() {
  formMode.value = null;
  editingId.value = null;
  resetFormModels();
}

function onFormPresetChange() {
  // Preset is disabled in edit mode, so this only fires when adding.
  const p = presets.value.find((x) => x.key === providerForm.value.preset);
  if (!p) return;
  providerForm.value.name = providerForm.value.name || p.label;
  providerForm.value.base_url = p.base_url;
  providerForm.value.model = p.model;
  resetFormModels();
}

async function fetchFormModels() {
  if (!providerForm.value.base_url) return;
  formModelsLoading.value = true;
  try {
    // Edit mode without a freshly-typed key → use the saved key (per-id endpoint).
    // Otherwise (add mode, or edit with a new key) → preview endpoint.
    const models =
      formMode.value === "edit" && editingId.value != null && !providerForm.value.api_key
        ? await listProviderModels(editingId.value)
        : await previewProviderModels(
            providerForm.value.base_url,
            providerForm.value.api_key || undefined,
          );
    formModels.value = models.map((m) => m.id).sort();
    formModelCustom.value = false;
    const n = formModels.value.length;
    emit("toast", "success", `Found ${n} model${n === 1 ? "" : "s"}`);
  } catch (e) {
    emit("toast", "error", `Models: ${apiErrMsg(e)}`);
  } finally {
    formModelsLoading.value = false;
  }
}

function onFormModelChange(value: string) {
  if (value === "__custom__") {
    formModelCustom.value = true; // current model stays in the free-text input
    return;
  }
  providerForm.value.model = value;
}

async function saveProvider() {
  providerSaving.value = true;
  try {
    if (formMode.value === "add") {
      await createProvider({
        name: providerForm.value.name.trim() || providerForm.value.preset,
        preset: providerForm.value.preset,
        base_url: providerForm.value.base_url.trim(),
        model: providerForm.value.model.trim(),
        api_key: providerForm.value.api_key || undefined,
        is_active: providers.value.length === 0, // first provider auto-activates
      });
      emit("toast", "success", "Provider added");
    } else if (formMode.value === "edit" && editingId.value != null) {
      const patch: AIProviderUpdate = {
        name: providerForm.value.name.trim() || providerForm.value.preset,
        base_url: providerForm.value.base_url.trim(),
        model: providerForm.value.model.trim(),
      };
      // Only send the key when the user typed a new one — blank means "keep".
      if (providerForm.value.api_key) patch.api_key = providerForm.value.api_key;
      await updateProvider(editingId.value, patch);
      emit("toast", "success", "Provider saved");
    }
    closeForm();
    await loadProviders();
  } catch (e) {
    emit("toast", "error", `Save failed: ${apiErrMsg(e)}`);
  } finally {
    providerSaving.value = false;
  }
}

async function removeProvider(p: AIProvider) {
  if (!window.confirm(`Delete provider "${p.name}"? This cannot be undone.`)) return;
  try {
    await deleteProvider(p.id);
    if (editingId.value === p.id) closeForm();
    await loadProviders();
    emit("toast", "info", "Provider removed");
  } catch (e) {
    emit("toast", "error", apiErrMsg(e));
  }
}

async function toggleActive(p: AIProvider) {
  // Toggle = is_active. Turning the active provider off leaves none active
  // (→ local Ollama fallback); turning one on deactivates the others.
  try {
    if (p.is_active) {
      await updateProvider(p.id, { is_active: false });
    } else {
      await activateProvider(p.id);
    }
    await loadProviders();
  } catch (e) {
    emit("toast", "error", apiErrMsg(e));
  }
}

async function testConn(p: AIProvider) {
  testingId.value = p.id;
  try {
    const r = await testProvider(p.id);
    emit("toast", "success", `Connected — ${r.model}`);
  } catch (e) {
    emit("toast", "error", `Test failed: ${apiErrMsg(e)}`);
  } finally {
    testingId.value = null;
  }
}

onMounted(() => {
  loadAppSettings();
  loadOllamaModels();
  loadProviders();
});
</script>

<template>
  <div
    v-if="activeProviderIsCloud && !cloudWarningDismissed"
    class="mb-3 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] leading-snug text-amber-200"
  >
    <AlertTriangle :size="14" class="mt-px shrink-0" />
    <div class="flex-1">
      <strong class="font-medium">Cloud AI is on.</strong> Running any AI tool on an
      entry or note sends its text to <strong>{{ activeCloudProviderName }}</strong> —
      it leaves your device. Switch the active provider to local Ollama to keep
      everything on your machine. See <em>Privacy</em> for the full picture.
    </div>
    <button
      class="shrink-0 text-amber-200/70 hover:text-amber-200"
      title="Dismiss"
      @click="cloudWarningDismissed = true"
    >
      ✕
    </button>
  </div>
  <SettingsSection
    title="AI Providers"
    :icon="Sparkles"
    description="Cloud providers (OpenAI-compatible). The first one you add becomes active; Ollama below is the local fallback."
    setting-key="AI Providers"
  >
    <div v-if="providers.length" class="space-y-1.5">
      <div
        v-for="p in providers"
        :key="p.id"
        class="rounded-md bg-surface-hover"
        :class="formMode === 'edit' && editingId === p.id ? 'ring-1 ring-accent/60' : ''"
      >
        <div class="flex items-center gap-2 px-2 py-1.5">
          <ToggleSwitch
            :model-value="p.is_active"
            :title="p.is_active ? 'Active — AI tools route here' : 'Set as active'"
            @update:model-value="toggleActive(p)"
          />
          <div class="flex-1 min-w-0">
            <div class="text-[12px] text-text-primary truncate flex items-center gap-1.5">
              <span class="truncate">{{ p.name }}</span>
              <span
                v-if="p.is_active"
                class="shrink-0 text-[9px] px-1 py-px rounded bg-accent/15 text-accent"
                >active</span
              >
            </div>
            <div class="text-[10px] text-text-muted truncate">
              {{ p.model }} · {{ p.base_url
              }}<span v-if="!p.has_key && p.preset !== 'ollama'"> · no key</span>
            </div>
          </div>
          <SButton variant="ghost" size="xs" :disabled="testingId === p.id" @click="testConn(p)">
            <Loader v-if="testingId === p.id" :size="11" class="animate-spin" /> Test
          </SButton>
          <SButton
            variant="ghost"
            size="xs"
            :disabled="formMode !== null"
            title="Edit provider"
            @click="openEditForm(p)"
          >
            Edit
          </SButton>
          <SButton
            variant="ghost"
            size="xs"
            class="!text-text-muted hover:!text-danger"
            title="Delete provider"
            @click="removeProvider(p)"
          >
            Delete
          </SButton>
        </div>
      </div>
    </div>
    <p v-else-if="formMode !== 'add'" class="text-[11px] text-text-muted">
      No cloud providers — AI tools use local Ollama.
    </p>

    <!-- Shared inline Add / Edit form -->
    <div v-if="formMode !== null" class="mt-2 space-y-1.5 p-2 rounded-md border border-border">
      <div class="flex items-center gap-1.5 text-[11px] text-text-secondary">
        <Sparkles :size="12" />
        {{ formMode === "add" ? "Add provider" : "Edit provider" }}
      </div>
      <div class="flex gap-1.5">
        <select
          v-model="providerForm.preset"
          class="settings-select flex-1"
          :disabled="formMode === 'edit'"
          @change="onFormPresetChange"
        >
          <option v-for="pr in presets" :key="pr.key" :value="pr.key">{{ pr.label }}</option>
        </select>
        <input v-model="providerForm.name" placeholder="Name" class="settings-input flex-1" />
      </div>
      <input v-model="providerForm.base_url" placeholder="Base URL (…/v1)" class="settings-input w-full" />
      <!-- Model: dropdown once a list is fetched, else free text. ↻ fetches from the provider. -->
      <div class="flex items-center gap-1.5">
        <select
          v-if="formModels.length && !formModelCustom"
          class="settings-select flex-1"
          :value="providerForm.model"
          @change="onFormModelChange(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="m in formModelOptions" :key="m" :value="m">{{ m }}</option>
          <option value="__custom__">Custom…</option>
        </select>
        <input v-else v-model="providerForm.model" placeholder="Model id" class="settings-input flex-1" />
        <SButton
          variant="ghost"
          size="xs"
          :disabled="formModelsLoading || !providerForm.base_url"
          title="Fetch available models from provider"
          @click="fetchFormModels"
        >
          <Loader v-if="formModelsLoading" :size="12" class="animate-spin" />
          <RefreshCw v-else :size="12" />
        </SButton>
      </div>
      <input
        v-model="providerForm.api_key"
        type="password"
        :placeholder="
          formMode === 'edit'
            ? 'API key (leave blank to keep current)'
            : 'API key (stored encrypted)'
        "
        class="settings-input w-full"
      />
      <div class="flex gap-1.5">
        <SButton
          variant="primary"
          :disabled="providerSaving || !providerForm.base_url || !providerForm.model"
          @click="saveProvider"
        >
          <Loader v-if="providerSaving" :size="11" class="animate-spin" />
          {{ formMode === "add" ? "Add provider" : "Save" }}
        </SButton>
        <SButton variant="ghost" @click="closeForm">Cancel</SButton>
      </div>
    </div>
    <SButton v-else variant="outline" size="xs" :icon="Sparkles" @click="openAddForm">
      Add provider
    </SButton>
  </SettingsSection>

  <SettingsSection
    title="AI Configuration"
    :icon="Brain"
    description="Local AI model and feature settings"
    setting-key="Ollama URL"
    reset-label="Reset"
    @reset="resetAIDefaults"
  >
    <template v-if="settingsLoading"><SkeletonCard :lines="4" /></template>

    <template v-else-if="appSettings">
      <SettingGroup label="Connection">
        <SettingRow
          :icon="Link"
          label="Ollama URL"
          description="Base URL of your local Ollama server."
        >
          <input
            v-model="appSettings.ai.ollama_base_url"
            placeholder="http://localhost:11434"
            class="settings-input w-44"
          />
        </SettingRow>
        <div class="flex items-center gap-2 pl-[31px]">
          <SButton
            variant="outline"
            :disabled="connTesting"
            @click="testConnection"
          >
            <Loader v-if="connTesting" :size="12" class="animate-spin" /><Wifi
              v-else
              :size="12"
            />
            Test Connection
          </SButton>
          <span
            v-if="connStatus"
            class="flex items-center gap-1 text-[11px]"
            :class="connStatus.ok ? 'text-green-400' : 'text-red-400'"
          >
            <Wifi v-if="connStatus.ok" :size="11" /><WifiOff
              v-else
              :size="11"
            />
            {{ connStatus.ok ? "Connected" : "Unreachable" }}
          </span>
        </div>
      </SettingGroup>

      <SettingGroup label="Models">
        <SettingRow
          :icon="Sparkles"
          label="Chat model"
          description="Used for suggestions, summaries, and prompts."
        >
          <select
            v-model="appSettings.ai.ollama_model"
            class="settings-select max-w-44"
          >
            <option v-for="m in ollamaModels" :key="m.name" :value="m.name">
              {{ m.name }} {{ m.size ? `(${formatModelSize(m.size)})` : "" }}
            </option>
            <option
              v-if="
                !ollamaModels.some(
                  (m) => m.name === appSettings!.ai.ollama_model,
                )
              "
              :value="appSettings.ai.ollama_model"
            >
              {{ appSettings.ai.ollama_model }} (current)
            </option>
          </select>
        </SettingRow>
        <div
          v-if="selectedModelIsReasoning"
          class="flex items-start gap-1.5 pl-[31px] text-[10.5px] leading-snug text-amber-400"
        >
          <AlertTriangle :size="12" class="shrink-0 mt-px" />
          <span>
            Reasoning models (e.g. qwen3, deepseek-r1) can stall or hang on
            machines without a GPU. For reliable editor AI, use a standard model
            like <strong class="font-medium">gemma3:4b</strong> or
            <strong class="font-medium">llama3.2:3b</strong>.
          </span>
        </div>
        <SettingRow
          :icon="Eye"
          label="Embedding model"
          description="Powers semantic search and similar-entry lookup."
        >
          <input
            v-model="appSettings.ai.ollama_embed_model"
            list="embed-models"
            placeholder="nomic-embed-text"
            class="settings-input w-44"
          />
          <datalist id="embed-models">
            <option v-for="m in availableEmbedModels" :key="m" :value="m" />
          </datalist>
        </SettingRow>
        <div class="flex items-center gap-2 pl-[31px]">
          <SButton
            variant="ghost"
            size="xs"
            :disabled="modelsRefreshing"
            @click="refreshModels"
          >
            <Loader
              v-if="modelsRefreshing"
              :size="11"
              class="animate-spin"
            /><RefreshCw v-else :size="11" /> Refresh model list
          </SButton>
          <span class="text-[10.5px] text-text-muted"
            >{{ ollamaModels.length }} available</span
          >
        </div>
      </SettingGroup>

      <SettingGroup label="Features">
        <div
          v-for="f in featureToggles"
          :key="f.key"
          class="flex items-start justify-between gap-3 py-1"
        >
          <div class="flex-1 min-w-0">
            <div
              class="text-[12px] text-text-secondary flex items-center gap-1.5"
            >
              {{ f.label }}
              <span
                v-if="f.needsEmbed"
                class="text-[9px] px-1 py-px rounded bg-accent/15 text-accent"
                >needs embed</span
              >
            </div>
            <p class="text-[10.5px] text-text-muted leading-snug mt-0.5">
              {{ f.desc }}
            </p>
          </div>
          <ToggleSwitch v-model="(appSettings.ai as any)[f.key]" />
        </div>
      </SettingGroup>

      <!-- Save (dirty-aware) -->
      <div class="flex items-center gap-2 pt-1">
        <SButton
          variant="primary"
          :disabled="aiSaving || !aiDirty"
          @click="saveAISettings"
        >
          <Loader v-if="aiSaving" :size="12" class="animate-spin" /> Save AI
          Settings
        </SButton>
        <span v-if="aiDirty" class="text-[10.5px] text-amber-500"
          >Unsaved changes</span
        >
      </div>

      <SettingGroup label="Download">
        <SettingRow
          :icon="DownloadIcon"
          label="Pull new model"
          description="Download a model into your local Ollama."
        >
          <div class="flex items-center gap-1.5">
            <input
              v-model="pullModelName"
              placeholder="e.g. llama3.2:3b"
              class="settings-input w-44"
            />
            <SButton
              variant="primary"
              :disabled="pulling || !pullModelName.trim()"
              @click="handlePullModel"
            >
              <Loader v-if="pulling" :size="12" class="animate-spin" /> Pull
            </SButton>
          </div>
        </SettingRow>
        <p v-if="pullStatus" class="text-[10.5px] text-text-muted pl-[31px]">
          {{ pullStatus }}
        </p>
      </SettingGroup>
    </template>
  </SettingsSection>

  <AccordionItem
    title="Themes & Insights"
    :icon="Brain"
    description="Discover patterns in your journaling"
  >
    <div class="space-y-3">
      <SettingRow label="Analyze journaling themes over">
        <div class="flex items-center gap-1.5">
          <select v-model.number="themesMonths" class="settings-select w-24">
            <option v-for="m in [1, 3, 6, 12, 24]" :key="m" :value="m">
              {{ m }} month{{ m > 1 ? "s" : "" }}
            </option>
          </select>
          <SButton
            variant="primary"
            :disabled="themesLoading"
            @click="fetchThemes"
          >
            <Loader
              v-if="themesLoading"
              :size="12"
              class="animate-spin"
            /><Sparkles v-else :size="12" /> Analyze
          </SButton>
        </div>
      </SettingRow>
      <div v-if="themes.length" class="space-y-2 max-h-60 overflow-y-auto">
        <div
          v-for="(t, i) in themes"
          :key="i"
          class="p-2.5 bg-surface-hover rounded-md space-y-1"
        >
          <div class="flex items-center justify-between">
            <span class="text-[12px] font-medium text-text-primary">{{
              t.theme
            }}</span>
            <span class="text-[11px] text-accent">{{ t.frequency }}</span>
          </div>
          <div
            v-if="t.months_mentioned.length"
            class="text-[10px] text-text-muted"
          >
            Months: {{ t.months_mentioned.join(", ") }}
          </div>
          <div v-if="t.insight" class="text-[11px] text-text-secondary">
            {{ t.insight }}
          </div>
        </div>
      </div>
      <div v-else-if="!themesLoading" class="text-center py-3">
        <Sparkles :size="18" class="mx-auto text-text-muted mb-1" />
        <p class="text-[11px] text-text-secondary">No theme analysis yet.</p>
        <p class="text-[10px] text-text-muted">
          Click Analyze to discover patterns in your entries.
        </p>
      </div>
    </div>
  </AccordionItem>
</template>
