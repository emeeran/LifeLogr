<script setup lang="ts">
import { ref, computed, nextTick, provide, watch } from "vue";
import { useLocalStorage } from "@vueuse/core";
import { useUiStore } from "../../stores/ui";
import {
  CheckCircle2,
  AlertTriangle,
  X,
  Info,
  Brain,
  Heart,
  Palette,
  Database,
  Search,
  Shield,
} from "lucide-vue-next";
import AppearanceTab from "./tabs/AppearanceTab.vue";
import AITab from "./tabs/AITab.vue";
import DataTab from "./tabs/DataTab.vue";
import PrivacyTab from "./tabs/PrivacyTab.vue";
import DedicationTab from "./tabs/DedicationTab.vue";
import AboutTab from "./tabs/AboutTab.vue";

// ── Tab navigation ──
const TAB_IDS = ["appearance", "ai", "data", "privacy", "dedication", "about"] as const;
// Map stale tab ids from the old 8-tab layout → the new 5-tab one, so an
// existing user's persisted selection isn't a blank screen after upgrade.
const LEGACY_TAB: Record<string, string> = {
  general: "appearance",
  notes: "appearance",
  features: "appearance",
  "data-backup": "data",
  diagnostics: "data",
};
function migrateTabId(id: string): string {
  return (TAB_IDS as readonly string[]).includes(id) ? id : LEGACY_TAB[id] ?? "appearance";
}
const _storedTab = useLocalStorage<string>("lifelogr-settings-tab", "appearance");
const activeTab = computed<string>({
  get: () => migrateTabId(_storedTab.value),
  set: (v) => {
    _storedTab.value = v;
  },
});
const tabs = [
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "ai", label: "AI", icon: Brain },
  { id: "data", label: "Data", icon: Database },
  { id: "privacy", label: "Privacy", icon: Shield },
  { id: "dedication", label: "Dedication", icon: Heart },
  { id: "about", label: "About", icon: Info },
] as const;

// Deep-linking: a component (e.g. the health banner) can request a Settings tab.
const ui = useUiStore();
if (ui.requestedSettingsTab) {
  activeTab.value = ui.requestedSettingsTab;
  ui.requestedSettingsTab = null;
}
watch(
  () => ui.requestedSettingsTab,
  (id) => {
    if (id) {
      activeTab.value = id;
      ui.requestedSettingsTab = null;
    }
  },
);

// ── Settings search ──
// A small index of {tab, keywords} drives two behaviours:
//   1. filtering the visible tabs (like before), and
//   2. "jump to + highlight" — when a query matches, we switch to that tab
//      and briefly pulse the first matching setting row.
const searchQuery = ref("");
const searchLower = computed(() => searchQuery.value.toLowerCase().trim());
const highlightKey = ref<string | null>(null);

interface SearchEntry {
  tab: string;
  label: string;
  keywords: string[];
}
const index: SearchEntry[] = [
  // ── Appearance ──
  {
    tab: "appearance",
    label: "Appearance",
    keywords: ["appearance", "dark mode", "theme", "font", "font family", "font size", "look", "night"],
  },
  { tab: "appearance", label: "Dark mode", keywords: ["dark mode", "dark", "light", "theme"] },
  { tab: "appearance", label: "Font family", keywords: ["font", "font family", "typeface"] },
  { tab: "appearance", label: "Font size", keywords: ["font size", "text size"] },
  { tab: "appearance", label: "Auto-save", keywords: ["autosave", "auto-save", "save", "interval"] },
  { tab: "appearance", label: "OCR language", keywords: ["ocr", "image text", "language"] },
  { tab: "appearance", label: "Default title", keywords: ["default title", "title"] },
  { tab: "appearance", label: "Search mode", keywords: ["search mode", "hybrid", "keyword", "semantic"] },
  { tab: "appearance", label: "Default template", keywords: ["template", "default template"] },
  { tab: "appearance", label: "Voice", keywords: ["voice", "tts", "read aloud", "speech", "text to speech"] },
  { tab: "appearance", label: "Speed", keywords: ["speed", "rate", "tts speed"] },
  { tab: "appearance", label: "Volume", keywords: ["volume", "tts volume"] },
  { tab: "appearance", label: "Preview voice", keywords: ["preview", "test voice"] },
  { tab: "appearance", label: "Keyboard shortcuts", keywords: ["shortcut", "keyboard", "hotkey"] },

  // ── AI ──
  { tab: "ai", label: "Ollama URL", keywords: ["ollama", "url", "connection", "ai url"] },
  { tab: "ai", label: "Chat model", keywords: ["chat model", "model", "llama"] },
  { tab: "ai", label: "Embedding model", keywords: ["embedding", "embed", "nomic", "semantic model"] },
  { tab: "ai", label: "Embeddings", keywords: ["embeddings", "vector"] },
  { tab: "ai", label: "Tag suggestions", keywords: ["tag suggestions", "auto tag", "tags"] },
  { tab: "ai", label: "Sentiment analysis", keywords: ["sentiment", "mood"] },
  { tab: "ai", label: "Summarization", keywords: ["summarization", "summary", "summarize"] },
  { tab: "ai", label: "Reflection prompts", keywords: ["reflection", "prompts", "prompt"] },
  { tab: "ai", label: "Writer's block helper", keywords: ["writer block", "writer", "block", "suggestion"] },
  { tab: "ai", label: "Pull model", keywords: ["pull model", "download model", "install model"] },
  { tab: "ai", label: "Themes & Insights", keywords: ["themes", "insights", "patterns"] },

  // ── Data ──
  {
    tab: "data",
    label: "Storage",
    keywords: ["storage", "disk", "database size", "usage", "entries count", "media"],
  },
  {
    tab: "data",
    label: "Import entries",
    keywords: ["import", "import entries", "zip", "json", "html", "diarium import"],
  },
  {
    tab: "data",
    label: "Export",
    keywords: ["export", "markdown", "pdf", "html export", "diarium export", "backup export"],
  },
  { tab: "data", label: "Remove duplicates", keywords: ["duplicate", "duplicates", "deduplicate", "dedupe"] },
  { tab: "data", label: "Compact database", keywords: ["compact", "vacuum", "database maintenance"] },
  { tab: "data", label: "Check integrity", keywords: ["integrity", "corrupt", "check database"] },
  { tab: "data", label: "Local backup", keywords: ["local backup", "archive", "tar", "manual backup"] },
  { tab: "data", label: "Scheduled backup", keywords: ["auto backup", "scheduled", "schedule", "automatic", "cron"] },
  {
    tab: "data",
    label: "Cloud backup",
    keywords: ["cloud", "google drive", "webdav", "onedrive", "dropbox", "nas", "sync"],
  },
  {
    tab: "data",
    label: "Diagnostics",
    keywords: ["diagnostics", "health", "system status", "rebuild index", "search index"],
  },

  // ── Privacy ──
  {
    tab: "privacy",
    label: "What leaves your machine",
    keywords: [
      "privacy",
      "leaves device",
      "egress",
      "cloud",
      "data leaves",
      "local",
      "offline",
      "encryption",
      "secret key",
      "what leaves",
    ],
  },

  // ── Dedication ──
  {
    tab: "dedication",
    label: "Memorial",
    keywords: [
      "dedication",
      "memorial",
      "remembrance",
      "remember",
      "tribute",
      "in loving memory",
      "candle",
      "reflection",
      "in memory",
      "title",
    ],
  },

  // ── About ──
  { tab: "about", label: "Version", keywords: ["version", "about"] },
  { tab: "about", label: "Release notes", keywords: ["release notes", "changelog", "what's new"] },
  { tab: "about", label: "Updates", keywords: ["update", "updates", "check for updates", "release"] },
  {
    tab: "about",
    label: "System setup",
    keywords: ["system setup", "dependencies", "ollama install", "gstreamer", "audio recording"],
  },
  {
    tab: "about",
    label: "Reset database",
    keywords: ["reset", "reset database", "erase", "danger", "clear", "delete all"],
  },
];

const filteredTabs = computed(() => {
  if (!searchLower.value) return tabs;
  const matched = new Set(
    index
      .filter(
        (e) =>
          e.label.toLowerCase().includes(searchLower.value) ||
          e.keywords.some(
            (k) => k.includes(searchLower.value) || searchLower.value.includes(k),
          ),
      )
      .map((e) => e.tab),
  );
  return tabs.filter(
    (t) =>
      matched.has(t.id) || t.label.toLowerCase().includes(searchLower.value),
  );
});

// Best matching entry for the current query (for "jump to" highlight).
const bestMatch = computed<SearchEntry | null>(() => {
  if (!searchLower.value) return null;
  // Prefer a label that starts with the query, then any label/keyword match.
  const starts = index.find((e) => e.label.toLowerCase().startsWith(searchLower.value));
  if (starts) return starts;
  const contains = index.find(
    (e) =>
      e.label.toLowerCase().includes(searchLower.value) ||
      e.keywords.some((k) => k.includes(searchLower.value)),
  );
  return contains ?? null;
});

/** When the user presses Enter in the search box, jump to the best match and
 *  briefly highlight its row. */
async function jumpToMatch() {
  const m = bestMatch.value;
  if (!m) return;
  activeTab.value = m.tab;
  searchQuery.value = "";
  highlightKey.value = m.label;
  await nextTick();
  setTimeout(() => {
    highlightKey.value = null;
  }, 1800);
  // Scroll the highlighted element into view.
  await nextTick();
  const el = document.querySelector('[data-setting-key="' + m.label + '"]');
  if (el)
    (el as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
}

// ── Toast ──
const toast = ref<{
  type: "success" | "error" | "info";
  message: string;
} | null>(null);
let toastTimer: ReturnType<typeof setTimeout> | null = null;
function showToast(type: "success" | "error" | "info", message: string) {
  if (toastTimer) clearTimeout(toastTimer);
  toast.value = { type, message };
  toastTimer = setTimeout(() => {
    toast.value = null;
  }, 3000);
}

provide("settings-highlight", highlightKey);
</script>
<template>
  <div class="flex flex-col h-full">
    <div class="px-4 py-2.5 border-b border-border">
      <h2 class="text-xs font-semibold text-text-primary tracking-wide">
        Settings
      </h2>
    </div>

    <div class="flex flex-1 min-h-0">
      <nav
        class="w-40 shrink-0 border-r border-border py-2 px-2 space-y-0.5 overflow-y-auto"
        aria-label="Settings sections"
      >
        <div class="mb-2">
          <div
            class="flex items-center gap-1.5 bg-surface border border-border rounded-md px-2 py-1"
          >
            <Search
              :size="12"
              class="text-text-muted shrink-0"
              aria-hidden="true"
            />
            <input
              v-model="searchQuery"
              placeholder="Search..."
              class="bg-transparent text-[11px] text-text-primary outline-none w-full placeholder-text-muted"
              @keydown.enter="jumpToMatch"
            />
            <button
              v-if="searchQuery"
              @click="searchQuery = ''"
              class="text-text-muted hover:text-text-primary cursor-pointer shrink-0"
              aria-label="Clear search"
            >
              <X :size="12" />
            </button>
          </div>
          <p v-if="searchQuery" class="text-[9px] text-text-muted mt-1 px-1">
            Press Enter to jump
          </p>
        </div>
        <button
          v-for="tab in filteredTabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          :aria-current="activeTab === tab.id ? 'page' : undefined"
          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-[12px] font-medium cursor-pointer transition-colors"
          :class="
            activeTab === tab.id
              ? 'bg-accent/15 text-accent'
              : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
          "
        >
          <component :is="tab.icon" :size="14" aria-hidden="true" />
          {{ tab.label }}
        </button>
        <div
          v-if="!filteredTabs.length"
          class="px-2 py-2 text-[11px] text-text-muted text-center"
        >
          No matching settings.
        </div>
      </nav>

      <div
        class="flex-1 min-h-0"
        :class="
          activeTab === 'dedication'
            ? 'overflow-hidden'
            : 'overflow-y-auto px-5 py-3 space-y-3'
        "
      >
        <AppearanceTab v-if="activeTab === 'appearance'" @toast="showToast" />
        <AITab v-if="activeTab === 'ai'" @toast="showToast" />
        <DataTab v-if="activeTab === 'data'" @toast="showToast" />
        <PrivacyTab v-if="activeTab === 'privacy'" />
        <DedicationTab v-if="activeTab === 'dedication'" />
        <AboutTab v-if="activeTab === 'about'" @toast="showToast" />
      </div>
    </div>

    <Transition name="toast">
      <div
        v-if="toast"
        class="absolute bottom-3 left-3 right-3 flex items-center gap-2 px-3 py-1.5 rounded-md border text-[12px]"
        :class="{
          'bg-green-900/80 border-green-700 text-green-200': toast.type === 'success',
          'bg-red-900/80 border-red-700 text-red-200': toast.type === 'error',
          'bg-surface border-border text-text-primary': toast.type === 'info',
        }"
      >
        <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
        <AlertTriangle v-else-if="toast.type === 'error'" :size="14" />
        <Info v-else :size="14" />
        {{ toast.message }}
        <button class="ml-auto p-0.5 cursor-pointer" @click="toast = null">
          <X :size="12" />
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
