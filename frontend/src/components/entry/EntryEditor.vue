<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from "vue";
import { useEntriesStore } from "../../stores/entries";
import { useTagsStore } from "../../stores/tags";
import { useUiStore } from "../../stores/ui";
import {
  X,
  Eye,
  Edit3,
  Minimize2,
  Maximize2,
  Search,
  ChevronUp,
  ChevronDown,
  Sparkles,
  Plus,
  Lock,
  Trash2,
  Tag,
  Volume2,
  Paperclip,
  LayoutTemplate,
  Loader,
  Pause,
} from "lucide-vue-next";
import EncryptionBadge from "./EncryptionBadge.vue";
import EditorToolbar from "./EditorToolbar.vue";
import EditorStatusBar from "./EditorStatusBar.vue";
import EditorContextMenu from "./EditorContextMenu.vue";
import TagList from "../tags/TagList.vue";
import MediaViewer from "../media/MediaViewer.vue";
import MediaGrid from "../media/MediaGrid.vue";
import TemplatePicker from "../templates/TemplatePicker.vue";
import EmojiPicker from "../common/EmojiPicker.vue";
import { useTemplatesStore } from "../../stores/templates";
import { aiStatus, suggestTags } from "../../api/ai";
import { encryptText, decryptText } from "../../api/encryption";
import { ttsApi } from "../../api/tts";
import { useDragDrop } from "../../composables/useDragDrop";
import { useLocalStorage } from "@vueuse/core";
import { useMarkdownPreview } from "../../composables/useMarkdownPreview";
import { useRichTextEditor } from "../../composables/useRichTextEditor";
import { useAttachments } from "../../composables/useAttachments";
import { useAutoSave } from "../../composables/useAutoSave";
import {
  useRecordings,
  provideRecordings,
} from "../../composables/useRecordings";
import FloatingRecorder from "../recordings/FloatingRecorder.vue";
import EntryRecordings from "../recordings/EntryRecordings.vue";
import FloatingPlayback from "../recordings/FloatingPlayback.vue";

const entries = useEntriesStore();
const ui = useUiStore();

const isNew = computed(() => ui.editingEntryId === -1);
const hasEntry = computed(
  () => ui.editingEntryId != null && ui.editingEntryId > 0,
);

// ── Voice recordings: floating recorder + embedded memo list + floating player ──
// One shared instance (provided below) keeps all three UI pieces in sync. Capture
// itself runs in the backend; this only drives the UI + local playback <audio>.
async function ensureSavedForRecording(): Promise<boolean> {
  if (hasEntry.value) return true;
  await save();
  return hasEntry.value;
}
const recordingsState = useRecordings(
  () => ui.editingEntryId,
  ensureSavedForRecording,
);
provideRecordings(recordingsState);
const title = ref("");
const body = ref("");
const tagIds = ref<number[]>([]);
const entryDate = ref("");
const showPreview = ref(false);
const fullscreen = ref(false);
const textarea = ref<HTMLTextAreaElement | null>(null);
const showTemplates = ref(false);
const showEmoji = ref(false);
const viewerOpen = ref(false);
const viewerIndex = ref(0);
const showTagDropdown = ref(false);
const aiAvailable = ref<boolean | null>(null);
const suggestedTags = ref<string[]>([]);
const suggestingTags = ref(false);
const ttsPlaying = ref(false);
const ttsLoading = ref(false);
let ttsAudio: HTMLAudioElement | null = null;
const isEncrypted = ref(false);
const focusMode = ref(false);
const typewriterMode = ref(false);
const showToolbar = ref(false);
const showContextMenu = ref(false);
const contextMenuPos = ref({ x: 0, y: 0 });
const defaultTemplateId = useLocalStorage<number | null>(
  "lifelogr-default-template",
  null,
);
// Which template the current entry was created from. Captured at creation
// (default auto-apply or explicit pick) and sent once on create, powering the
// Timeline template filter. null = blank / no template.
const selectedTemplateId = ref<number | null>(null);

// ── Shared editing core (selection, formatting, history, find, AI, shortcuts) ──
const {
  cacheSelection,
  clearSelCache,
  startSelCache,
  getSelection,
  applyToSelection,
  insertAtCursor,
  actions,
  activeFormats,
  undoStack,
  redoStack,
  pushHistory,
  showFind,
  findQuery,
  replaceQuery,
  findIndex,
  findCount,
  jumpToMatch,
  replaceOne,
  replaceAll,
  onTextareaKeydown,
  onShortcutKeydown,
  onInput,
  aiLoading,
  aiResult,
  aiResultMode,
  aiParamValue,
  runAiTool,
  aiResultReplace,
  aiResultInsert,
  aiResultRetry,
  aiResultCopy,
  applyToolParam,
  clearAiResult,
} = useRichTextEditor({
  body,
  textarea,
  onChange: markChanged,
  onSave: save,
});
const { attachments, loadAttachments, handleFileUpload, removeAttachment } =
  useAttachments(
    () => hasEntry.value,
    () => ui.editingEntryId ?? null,
    () => entries.refreshAll(),
  );
const fileInput = ref<HTMLInputElement | null>(null);

// Drag & Drop
const { isDragging, handlers: dragHandlers } = useDragDrop();

// Auto-save composable
const { triggerAutosave, saveState: saveActive } = useAutoSave({
  isNew,
  hasEntry,
  body,
  title,
  entryDate,
  tagIds,
  templateId: () => selectedTemplateId.value,
  editingEntryId: computed(() => ui.editingEntryId),
  snapshot,
  createEntry: (data) => entries.createEntry(data),
  updateEntry: (id, data) => entries.updateEntry(id, data),
  setEditingEntryId: (id) => {
    ui.editingEntryId = id;
  },
});

function errMsg(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

// ── Dirty tracking ──
const dirty = ref(false);
const savedSnapshot = ref("");

function markDirty() {
  dirty.value = true;
  ui.editorIsDirty = true;
}

/** Core onChange hook: mark dirty + (journal-only) typewriter scroll + autosave. */
function markChanged() {
  markDirty();
  if (typewriterMode.value) {
    nextTick(() => {
      const el = textarea.value;
      if (!el) return;
      const { selectionStart } = el;
      const lines = body.value.slice(0, selectionStart).split("\n").length;
      const lineHeight = 24; // approximate px
      const targetScroll = lines * lineHeight - el.clientHeight / 2;
      el.scrollTo({ top: targetScroll, behavior: "smooth" });
    });
  }
  triggerAutosave();
}

function snapshot() {
  savedSnapshot.value = JSON.stringify({
    body: body.value,
    title: title.value,
    tagIds: tagIds.value,
  });
  dirty.value = false;
  ui.editorIsDirty = false;
}

function isDirty(): boolean {
  if (dirty.value) return true;
  const current = JSON.stringify({
    body: body.value,
    title: title.value,
    tagIds: tagIds.value,
  });
  return current !== savedSnapshot.value;
}

// ── Undo / Redo history ── (extracted to useEditorHistory composable)
// ── Find & Replace ── (extracted to useFindReplace composable)

// ── Stats ──
const stats = computed(() => {
  const text = body.value;
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const lines = text ? text.split("\n").length : 0;
  const paragraphs = text.trim() ? text.trim().split(/\n\s*\n/).length : 0;
  const readMins = Math.max(1, Math.ceil(words / 200));
  return { chars, words, lines, paragraphs, readMins };
});

const { renderedPreview } = useMarkdownPreview(
  () => body.value,
  () => showPreview.value,
);

// ── Load entry data ──
async function loadEntry() {
  body.value = "";
  title.value = "";
  tagIds.value = [];
  selectedTemplateId.value = null;

  if (isNew.value) {
    if (ui.newEntryDate) {
      entryDate.value = ui.newEntryDate;
    } else {
      const d = new Date();
      entryDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }
    // Auto-apply default template
    try {
      const store = useTemplatesStore();
      await store.fetchAll();
      // If no default template selected yet, auto-pick the first built-in one
      if (!defaultTemplateId.value && store.templates.length) {
        const firstBuiltin = store.templates.find((t) => t.is_builtin);
        if (firstBuiltin) defaultTemplateId.value = firstBuiltin.id;
      }
      if (defaultTemplateId.value) {
        const tmpl = store.templates.find(
          (t) => t.id === defaultTemplateId.value,
        );
        if (tmpl) {
          body.value = tmpl.body;
          if (!title.value) title.value = tmpl.name;
          selectedTemplateId.value = tmpl.id;
        }
      }
    } catch {
      /* ignore */
    }
    // Apply default title if no template set one
    if (!title.value && ui.defaultTitle) {
      title.value = ui.defaultTitle;
    }
  } else if (ui.editingEntryId) {
    const entry = await entries.fetchEntry(ui.editingEntryId!);
    if (entry) {
      isEncrypted.value = entry.is_encrypted;
      if (entry.is_encrypted) {
        body.value = "";
        title.value = entry.title ?? "";
      } else {
        body.value = entry.body;
        title.value = entry.title ?? "";
      }
      tagIds.value = entry.tags.map((t) => t.id);
      entryDate.value = entry.entry_date;
      selectedTemplateId.value = entry.template_id;
    }
  }
  pushHistory();
  snapshot();
  loadAttachments();
}

onMounted(() => {
  loadEntry();
  window.addEventListener("click", async (e) => {
    // Don't dismiss while AI is running
    if (aiLoading.value) return;
    // If AI result panel is showing, clear it (dismisses without action)
    if (aiResult.value) {
      clearAiResult();
    }
    showContextMenu.value = false;
    const target = e.target as HTMLElement;
    if (target.classList.contains("enc-block")) {
      const enc = target.getAttribute("data-enc");
      if (!enc) return;
      const passphrase = prompt("Enter passphrase to decrypt:");
      if (!passphrase) return;
      try {
        const res = await decryptText(enc, passphrase);
        target.textContent = res.decrypted;
        target.classList.remove("bg-accent/10", "text-accent");
        target.classList.add("bg-surface-hover", "text-text-primary");
      } catch (e: unknown) {
        alert("Decryption failed: wrong passphrase?");
      }
    }
  });
});
onUnmounted(() => {
  window.removeEventListener("click", () => {
    showContextMenu.value = false;
  });
});
watch([() => ui.editingEntryId, () => ui.newEntryDate], () => {
  loadEntry();
  loadAttachments();
});

// Check AI availability once
aiStatus()
  .then((s) => {
    aiAvailable.value = s.ollama_available && s.model_loaded;
  })
  .catch(() => {
    aiAvailable.value = false;
  });

async function onEncryptionChange(encrypted: boolean) {
  isEncrypted.value = encrypted;
  await loadEntry();
}

// ── Fullscreen escape ──
function onContextMenu(e: MouseEvent) {
  e.preventDefault();
  // Cache selection immediately before blur fires — right-click can change selection
  cacheSelection();
  contextMenuPos.value = { x: e.clientX, y: e.clientY - 12 };
  showContextMenu.value = true;
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== "Escape") return;

  // Close active overlays in priority order
  if (showTemplates.value) {
    showTemplates.value = false;
    return;
  }
  if ((showContextMenu.value || aiResult.value) && !aiLoading.value) {
    clearAiResult();
    return;
  }
  if (ui.activeDrawer) {
    ui.closeDrawer();
    return;
  }
  if (showEmoji.value) {
    showEmoji.value = false;
    return;
  }
  if (viewerOpen.value) {
    viewerOpen.value = false;
    return;
  }
  if (showTagDropdown.value) {
    showTagDropdown.value = false;
    return;
  }
  if (showFind.value) {
    showFind.value = false;
    return;
  }
  if (fullscreen.value) {
    fullscreen.value = false;
    return;
  }

  // Close editor panel entirely
  close();
}

onMounted(() => document.addEventListener("keydown", onGlobalKeydown));
onUnmounted(() => document.removeEventListener("keydown", onGlobalKeydown));

defineExpose({
  isDirty,
  save,
  body,
  onInput,
  hasEntry,
  entryId: computed(() => ui.editingEntryId),
  attachments,
  handleFileUpload,
  removeAttachment,
  loadAttachments,
  triggerFileInput: () => fileInput.value?.click(),
  openViewer: (index: number) => {
    viewerIndex.value = index;
    viewerOpen.value = true;
  },
  getSelection,
  applyToSelection,
});

// ── Save ──
async function save() {
  try {
    if (isNew.value) {
      if (!body.value.trim() && !title.value.trim()) {
        return;
      }
      if (!title.value.trim()) {
        const t = prompt("Title for this entry:");
        if (t === null) return;
        title.value = t;
      }
      const entry = await entries.createEntry({
        entry_date: entryDate.value,
        title: title.value || null,
        body: body.value,
        tag_ids: tagIds.value.length ? tagIds.value : undefined,
        template_id: selectedTemplateId.value,
      });
      snapshot();
      entries.refreshAll();
      entries.currentEntry = entry;
      ui.detailPanelOpen = true;
      ui.startEditing(null);
    } else {
      // Allow empty body if a title is present (title-only / recording-only entries).
      if (!body.value.trim() && !title.value.trim()) {
        alert("Add a title or some text before saving");
        return;
      }
      await entries.updateEntry(ui.editingEntryId!, {
        title: title.value || null,
        body: body.value,
        tag_ids: tagIds.value,
      });
      snapshot();
      entries.refreshAll();
      ui.startEditing(null);
    }
  } catch (e: unknown) {
    console.error("[EntryEditor] save failed:", e);
    alert(`Save failed: ${errMsg(e)}`);
  }
}

function close() {
  entries.refreshAll();
  ui.startEditing(null);
}

function onEmojiSelect(emoji: string) {
  insertAtCursor(emoji);
  showEmoji.value = false;
}

function copyToClipboard() {
  const text = getSelection();
  if (text) navigator.clipboard.writeText(text);
}

function cutToClipboard() {
  const text = getSelection();
  if (text) {
    navigator.clipboard.writeText(text);
    applyToSelection("");
  }
}

async function onDropFiles(e: DragEvent) {
  const accepted = dragHandlers.onDrop(e);
  if (!accepted?.length) return;
  // Auto-save entry first if new
  if (!hasEntry.value) {
    await save();
    if (!hasEntry.value) return;
  }
  await handleFileUpload({
    length: accepted.length,
    item: (i: number) => accepted[i],
  } as any);
}

// ── Attachments ── (extracted to useAttachments composable)

async function openAttachDialog() {
  if (ui.activeDrawer === "attachments") {
    ui.closeDrawer();
    return;
  }
  if (!hasEntry.value) {
    await save();
    if (!hasEntry.value) return;
  }
  await loadAttachments();
  ui.activeDrawer = "attachments";
  nextTick(() => fileInput.value?.click());
}

// handleFileUpload, removeAttachment — extracted to useAttachments composable

async function encryptDecryptSelection() {
  const text = getSelection();
  if (!text) {
    alert("Please select some text.");
    return;
  }

  // Check if the selected text is an encrypted block
  const encMatch = text.match(/^<!--ENC\{(.+)\}-->$/s);
  if (encMatch) {
    // Decrypt mode
    const passphrase = prompt("Enter passphrase to decrypt:");
    if (!passphrase) return;
    try {
      const res = await decryptText(encMatch[1], passphrase);
      applyToSelection(res.decrypted);
    } catch (e: unknown) {
      alert(`Decryption failed: ${errMsg(e)}`);
    }
  } else {
    // Encrypt mode
    const passphrase = prompt("Enter a passphrase to encrypt this selection:");
    if (!passphrase) return;
    try {
      const res = await encryptText(text, passphrase);
      applyToSelection(`<!--ENC{${res.encrypted}}-->`);
    } catch (e: unknown) {
      alert(`Encryption failed: ${errMsg(e)}`);
    }
  }
}

// ── Inline AI tools (context menu) ── (extracted to useAiTools composable)
// runAiTool, aiResultReplace, aiResultInsert, aiResultRetry, aiResultCopy, clearAiResult — in composable

// ── Inline AI tools (context menu + drawer) — provided by useRichTextEditor ──

async function toggleTTS() {
  if (ttsPlaying.value) {
    if (ttsAudio) {
      ttsAudio.pause();
      ttsAudio = null;
    }
    ttsPlaying.value = false;
    return;
  }
  const text = [title.value, body.value].filter(Boolean).join("\n\n");
  if (!text.trim()) return;
  ttsLoading.value = true;
  try {
    if (hasEntry.value) {
      const url = ttsApi.entryUrl(ui.editingEntryId!);
      const res = await fetch(url);
      if (!res.ok) throw new Error(`TTS ${res.status}: ${await res.text()}`);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      ttsAudio = new Audio(blobUrl);
      ttsAudio.addEventListener("ended", () => URL.revokeObjectURL(blobUrl));
      ttsAudio.addEventListener("error", () => URL.revokeObjectURL(blobUrl));
    } else {
      const blob = await ttsApi.speakBlob(text);
      const blobUrl = URL.createObjectURL(blob);
      ttsAudio = new Audio(blobUrl);
      ttsAudio.addEventListener("ended", () => URL.revokeObjectURL(blobUrl));
      ttsAudio.addEventListener("error", () => URL.revokeObjectURL(blobUrl));
    }
    ttsAudio.addEventListener("ended", () => {
      ttsPlaying.value = false;
    });
    ttsAudio.addEventListener("error", () => {
      ttsPlaying.value = false;
    });
    ttsPlaying.value = true;
    ttsLoading.value = false;
    await ttsAudio.play();
  } catch (e: unknown) {
    alert(`Read Aloud failed: ${errMsg(e)}`);
  } finally {
    ttsLoading.value = false;
  }
}

async function handleDelete() {
  if (isNew.value) return;
  if (!confirm("Delete this entry?")) return;
  try {
    await entries.deleteEntry(ui.editingEntryId!);
  } catch {
    // Entry already gone — just close
  }
  entries.refreshAll();
  ui.startEditing(null);
}

function onTemplateSelect(t: { id: number; name: string; body: string }) {
  selectedTemplateId.value = t.id;
  if (!title.value.trim()) {
    title.value = t.name;
  }
  if (isNew.value || !body.value.trim()) {
    body.value = t.body;
  } else {
    body.value += "\n\n" + t.body;
  }
  onInput();
}

// ── AI Tag Suggestions ──
async function fetchSuggestedTags() {
  if (!body.value.trim()) return;
  suggestingTags.value = true;
  suggestedTags.value = [];
  try {
    const res = await suggestTags(body.value);
    suggestedTags.value = res.tags;
  } catch {
    /* ignore */
  } finally {
    suggestingTags.value = false;
  }
}

async function applySuggestedTag(name: string) {
  const tagsStore = useTagsStore();
  await tagsStore.fetchTree();
  const existing = tagsStore.tags.find(
    (t) => t.name.toLowerCase() === name.toLowerCase(),
  );
  if (existing) {
    if (!tagIds.value.includes(existing.id)) tagIds.value.push(existing.id);
  } else {
    const created = await tagsStore.createTag({ name });
    tagIds.value.push(created.id);
  }
  suggestedTags.value = suggestedTags.value.filter((t) => t !== name);
  onInput();
}

</script>

<template>
  <div
    class="flex flex-col h-full relative"
    :class="[
      fullscreen ? 'fixed inset-0 z-[100] bg-editor' : '',
      focusMode ? 'bg-editor' : '',
    ]"
    @dragenter="dragHandlers.onDragenter"
    @dragover="dragHandlers.onDragover"
    @dragleave="dragHandlers.onDragleave"
    @drop="onDropFiles"
  >
    <!-- Drag overlay -->
    <Transition name="drag">
      <div
        v-if="isDragging"
        class="absolute inset-0 z-[150] bg-accent/5 border-2 border-dashed border-accent/40 rounded-lg flex items-center justify-center pointer-events-none"
      >
        <div
          class="text-sm font-medium text-accent/80 flex flex-col items-center gap-1"
        >
          <Paperclip :size="24" />
          Drop files here
        </div>
      </div>
    </Transition>
    <!-- Header: Title + Date + New + controls -->
    <div
      class="flex items-center gap-2 px-3 py-1.5 border-b border-border"
      v-if="!focusMode"
    >
      <input
        v-model="title"
        class="flex-1 bg-transparent text-base font-semibold text-text-primary placeholder-text-muted/70 outline-none min-w-0"
        placeholder="Title"
        @input="onInput"
      />
      <input
        v-model="entryDate"
        type="date"
        class="bg-surface border border-border rounded px-1.5 py-0.5 text-[11px] text-text-primary shrink-0"
      />
      <button
        class="p-1 rounded hover:bg-accent/15 text-accent cursor-pointer transition-colors shrink-0"
        title="New entry"
        @click="ui.startEditing(-1)"
      >
        <Plus :size="14" />
      </button>
      <div class="flex items-center gap-0.5 shrink-0">
        <button
          v-if="!isNew"
          class="p-1 rounded hover:bg-surface-hover text-text-secondary hover:text-danger cursor-pointer transition-colors"
          title="Delete entry"
          @click="handleDelete"
        >
          <Trash2 :size="14" />
        </button>
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer transition-colors"
          :title="fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'"
          @click="fullscreen = !fullscreen"
        >
          <Minimize2 v-if="fullscreen" :size="14" />
          <Maximize2 v-else :size="14" />
        </button>
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer transition-colors"
          @click="close"
        >
          <X :size="14" />
        </button>
      </div>
    </div>

    <!-- Formatting toolbar (collapsible, closed by default) -->
    <div v-if="!showPreview && !focusMode" class="border-b border-border">
      <button
        class="flex items-center gap-1 w-full px-2 py-0.5 text-[10px] text-text-muted hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        @click="showToolbar = !showToolbar"
      >
        <ChevronDown
          v-if="!showToolbar"
          :size="10"
          class="transition-transform"
        />
        <ChevronUp v-else :size="10" class="transition-transform" />
        Formatting
      </button>
      <Transition name="toolbar-slide">
        <div v-if="showToolbar">
          <EditorToolbar
            :active-formats="activeFormats"
            :undo-count="undoStack.length"
            :redo-count="redoStack.length"
            :show-emoji="showEmoji"
            :show-find="showFind"
            :focus-mode="focusMode"
            :typewriter-mode="typewriterMode"
            :ui="ui"
            @action="
              (name: string) => {
                const fn = (actions as any)[name];
                if (fn) fn();
              }
            "
            @quick-emoji="onEmojiSelect"
            @toggle-emoji="showEmoji = !showEmoji"
            @toggle-find="showFind = !showFind"
            @toggle-focus="focusMode = !focusMode"
            @toggle-typewriter="typewriterMode = !typewriterMode"
          />
        </div>
      </Transition>
    </div>

    <!-- Find & Replace bar -->
    <div
      v-if="showFind"
      class="flex items-center gap-1.5 px-2 py-1 border-b border-border bg-surface"
    >
      <Search :size="12" class="text-text-muted shrink-0" />
      <input
        v-model="findQuery"
        class="flex-1 bg-transparent border-b border-border focus:border-accent px-1 py-0.5 text-xs text-text-primary outline-none"
        placeholder="Find..."
        @keydown="onShortcutKeydown"
      />
      <span class="text-[10px] text-text-muted whitespace-nowrap">
        {{ findIndex >= 0 ? findIndex + 1 : 0 }}/{{ findCount }}
      </span>
      <button
        class="p-0.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer"
        title="Previous"
        @click="jumpToMatch(-1)"
      >
        <ChevronUp :size="12" />
      </button>
      <button
        class="p-0.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer"
        title="Next"
        @click="jumpToMatch(1)"
      >
        <ChevronDown :size="12" />
      </button>
      <span class="w-px h-3 bg-border" />
      <input
        v-model="replaceQuery"
        class="flex-1 bg-transparent border-b border-border focus:border-accent px-1 py-0.5 text-xs text-text-primary outline-none"
        placeholder="Replace..."
      />
      <button
        class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer"
        @click="replaceOne"
      >
        Replace
      </button>
      <button
        class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer"
        @click="replaceAll"
      >
        All
      </button>
      <button
        class="p-0.5 rounded hover:bg-surface-hover text-text-muted cursor-pointer"
        @click="showFind = false"
      >
        <X :size="12" />
      </button>
    </div>

    <!-- Body + Panels -->
    <div class="flex-1 flex min-h-0 relative overflow-hidden">
      <!-- Main Editor Area -->
      <div class="flex-1 flex flex-col min-h-0">
        <!-- Textarea / Preview -->
        <div class="flex-1 overflow-y-auto relative min-h-0">
          <!-- Encrypted lock screen -->
          <div
            v-if="isEncrypted"
            class="flex flex-col items-center justify-center h-full gap-3 text-text-muted"
          >
            <Lock :size="32" class="text-accent opacity-60" />
            <div class="text-sm font-medium text-text-secondary">
              This entry is encrypted
            </div>
            <div class="text-xs">Click the unlock button to decrypt</div>
          </div>
          <template v-else>
            <textarea
              v-if="!showPreview"
              ref="textarea"
              v-model="body"
              class="w-full h-full resize-none bg-transparent p-4 text-text-primary outline-none leading-relaxed placeholder:text-text-muted/60"
              :style="{
                fontFamily: 'var(--editor-font)',
                fontSize: 'var(--editor-font-size)',
              }"
              placeholder="Write your thoughts..."
              @input="onInput"
              @keydown="onTextareaKeydown"
              @keydown.capture="onShortcutKeydown"
              @contextmenu="onContextMenu"
              @focus="clearSelCache"
              @blur="startSelCache"
            />
            <div
              v-else
              class="p-4 md-body max-w-none text-text-primary"
              :style="{
                fontFamily: 'var(--editor-font)',
                fontSize: 'var(--editor-font-size)',
              }"
              v-html="renderedPreview"
            />
          </template>
        </div>
      </div>
    </div>

    <!-- Voice memos embedded at the bottom of the entry -->
    <EntryRecordings v-if="!focusMode" />

    <!-- Media attachment thumbnails, pinned at the bottom of the entry -->
    <div
      v-if="!focusMode && hasEntry && !isEncrypted && attachments.length"
      class="px-3 pt-2 border-t border-border"
    >
      <MediaGrid
        :entry-id="ui.editingEntryId ?? 0"
        :media-count="attachments.length"
        @deleted="loadAttachments"
      />
    </div>

    <!-- Status bar + Bottom controls -->
    <div class="border-t border-border" v-if="!focusMode">
      <!-- Stats bar -->
      <EditorStatusBar
        :stats="stats"
        :save-state="saveActive"
        :has-content="!!body.trim()"
      />

      <!-- Controls bar: Edit/Preview + Tags + Save -->
      <div class="flex items-center gap-1.5 px-3 py-1.5 relative">
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors"
          :class="
            !showPreview
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary'
          "
          @click="showPreview = false"
        >
          <Edit3 :size="13" />
        </button>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors"
          :class="
            showPreview
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary'
          "
          @click="showPreview = true"
        >
          <Eye :size="13" />
        </button>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors relative"
          :class="
            tagIds.length
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary'
          "
          @click="showTagDropdown = !showTagDropdown"
          title="Tags"
        >
          <Tag :size="13" />
          <span v-if="tagIds.length" class="text-[9px]">{{
            tagIds.length
          }}</span>
        </button>

        <!-- Tag dropdown -->
        <div
          v-if="showTagDropdown && !isEncrypted"
          class="absolute bottom-full left-0 right-0 mb-1 mx-3 bg-surface border border-border rounded-lg shadow-xl p-2 z-50"
        >
          <TagList v-model="tagIds" />
          <!-- AI Tag Suggestions -->
          <div
            v-if="aiAvailable"
            class="mt-2 pt-2 border-t border-border space-y-1.5"
          >
            <button
              @click="fetchSuggestedTags"
              :disabled="suggestingTags || !body.trim()"
              class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 cursor-pointer"
            >
              <Loader v-if="suggestingTags" :size="10" class="animate-spin" />
              <Sparkles v-else :size="10" />
              {{ suggestingTags ? "Suggesting..." : "Suggest tags" }}
            </button>
            <div v-if="suggestedTags.length" class="flex flex-wrap gap-1">
              <button
                v-for="tag in suggestedTags"
                :key="tag"
                @click="applySuggestedTag(tag)"
                class="px-2 py-0.5 rounded-full text-[10px] bg-accent/15 text-accent hover:bg-accent/30 cursor-pointer transition-colors"
              >
                + {{ tag }}
              </button>
            </div>
          </div>
        </div>

        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Use template"
          @click="showTemplates = true"
        >
          <LayoutTemplate :size="13" />
        </button>

        <span class="w-px h-4 bg-border mx-0.5" />
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="
            ui.activeDrawer === 'ai'
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
          "
          title="AI Smart Actions"
          @click="ui.toggleDrawer('ai')"
        >
          <Sparkles :size="13" />
        </button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="
            ui.activeDrawer === 'attachments'
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
          "
          @click="openAttachDialog"
          title="Attach files"
        >
          <div class="flex items-center gap-0.5">
            <Paperclip :size="13" />
            <span v-if="attachments.length" class="text-[9px] leading-none">{{
              attachments.length
            }}</span>
          </div>
        </button>
        <input
          ref="fileInput"
          type="file"
          multiple
          accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.json"
          class="hidden"
          @change="handleFileUpload(($event.target as HTMLInputElement).files)"
        />
        <EncryptionBadge
          v-if="hasEntry"
          :entryId="ui.editingEntryId!"
          :isEncrypted="isEncrypted"
          @change="onEncryptionChange"
        />
        <button
          class="p-1 rounded cursor-pointer transition-colors disabled:opacity-50"
          :class="
            ttsPlaying
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
          "
          :disabled="ttsLoading || !body.trim()"
          @click="toggleTTS"
          :title="ttsPlaying ? 'Stop reading' : 'Read aloud'"
        >
          <Pause v-if="ttsPlaying" :size="13" />
          <Loader v-else-if="ttsLoading" :size="13" class="animate-spin" />
          <Volume2 v-else :size="13" />
        </button>

        <div class="flex-1" />
        <button
          class="px-4 py-1.5 rounded bg-accent text-white text-xs font-medium hover:bg-accent-hover transition-colors cursor-pointer"
          @click="save"
        >
          Save
        </button>
      </div>
    </div>

    <MediaViewer
      v-if="viewerOpen"
      :items="attachments"
      v-model:index="viewerIndex"
      @close="viewerOpen = false"
    />

    <EmojiPicker
      v-if="showEmoji"
      class="absolute top-20 right-4 z-50"
      @select="onEmojiSelect"
      @close="showEmoji = false"
    />

    <TemplatePicker
      v-if="showTemplates"
      @select="onTemplateSelect"
      @close="showTemplates = false"
    />

    <!-- Context Menu / AI Result Panel -->
    <EditorContextMenu
      :visible="showContextMenu"
      :position="contextMenuPos"
      :ai-loading="aiLoading"
      :ai-result="aiResult"
      :ai-result-mode="aiResultMode"
      :ai-param-value="aiParamValue"
      :selected-text="getSelection()"
      @close="showContextMenu = false"
      @copy="copyToClipboard"
      @cut="cutToClipboard"
      @bold="actions.bold()"
      @italic="actions.italic()"
      @encrypt="encryptDecryptSelection()"
      @open-ai-drawer="ui.toggleDrawer('ai')"
      @run-ai-tool="(mode: any) => runAiTool(mode)"
      @ai-result-replace="aiResultReplace"
      @ai-result-insert="aiResultInsert"
      @ai-result-retry="aiResultRetry"
      @ai-result-copy="aiResultCopy"
      @apply-tool-param="(value: string) => applyToolParam(value)"
      @close-result="clearAiResult"
    />

    <!-- Floating voice recorder + playback player -->
    <FloatingRecorder v-if="!focusMode" />
    <FloatingPlayback v-if="!focusMode" />
  </div>
</template>

<style scoped>
.toolbar-slide-enter-active,
.toolbar-slide-leave-active {
  transition: all 0.15s ease;
  overflow: hidden;
}
.toolbar-slide-enter-from,
.toolbar-slide-leave-to {
  max-height: 0;
  opacity: 0;
}
.toolbar-slide-enter-to,
.toolbar-slide-leave-from {
  max-height: 120px;
  opacity: 1;
}
.drag-enter-active,
.drag-leave-active {
  transition: all 0.2s ease;
}
.drag-enter-from,
.drag-leave-to {
  opacity: 0;
}
.md-body :deep(.enc-block) {
  display: inline-block;
  transition: all 0.2s;
}
.md-body :deep(.enc-block:hover) {
  opacity: 0.8;
  transform: translateY(-1px);
}
</style>
