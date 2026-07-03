<script setup lang="ts">
import { ref, watch, computed, nextTick, onMounted, onUnmounted } from 'vue'
import {
  Bold, Italic, Heading1, Heading2, List, Quote, Link as LinkIcon,
  Eye, Pencil, Sparkles, Pin, Trash2, Loader,
  Hash, ChevronDown, Check, Plus, Table,
} from 'lucide-vue-next'
import { useMarkdownPreview } from '../../composables/useMarkdownPreview'
import { useDragDrop } from '../../composables/useDragDrop'
import AiDrawerPanel from '../entry/AiDrawerPanel.vue'
import NoteEncryptionBadge from './NoteEncryptionBadge.vue'
import { useNotesStore } from '../../stores/notes'
import { tagsApi } from '../../api/tags'
import { notesApi } from '../../api/notes'
import { isTauri } from '../../api/client'
import type { NoteResponse, NoteFolderResponse, TagResponse } from '../../types'

const props = defineProps<{
  note: NoteResponse
  folders: NoteFolderResponse[]
  allTags: TagResponse[]
}>()
const emit = defineEmits<{ deleted: []; 'tag-created': [] }>()

const store = useNotesStore()
const { isDragging, handlers: dragHandlers } = useDragDrop()

// ── Local editable state (synced on note identity change only, so our own
//    autosave responses don't clobber in-flight typing) ──
const title = ref(props.note.title ?? '')
const body = ref(props.note.body)
const showPreview = ref(false)
const showAi = ref(false)
const showTags = ref(false)
const tagQuery = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const selStart = ref(0)
const selEnd = ref(0)
const saving = ref(false)
const savedAt = ref<number | null>(null)
let saveTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.note.id,
  () => {
    title.value = props.note.title ?? ''
    body.value = props.note.body
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  },
  { immediate: true },
)

// Debounced autosave for title/body.
watch([title, body], () => {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(doSave, 900)
})

async function doSave() {
  if (props.note.id == null) return
  if (title.value === (props.note.title ?? '') && body.value === props.note.body) return
  saving.value = true
  try {
    await store.updateNote(props.note.id, { title: title.value, body: body.value })
    savedAt.value = Date.now()
  } catch {
    /* store surfaces error */
  } finally {
    saving.value = false
  }
}

// ── Selection helpers (shared by AI tools + markdown formatting) ──
function updateSelection() {
  const el = textarea.value
  if (el) {
    selStart.value = el.selectionStart
    selEnd.value = el.selectionEnd
  }
}

function getSelection(): string {
  const el = textarea.value
  if (el && document.activeElement === el) return el.value.slice(el.selectionStart, el.selectionEnd)
  return body.value.slice(selStart.value, selEnd.value)
}

function applyText(text: string) {
  const el = textarea.value
  let s: number
  let e: number
  if (el && document.activeElement === el) {
    s = el.selectionStart
    e = el.selectionEnd
  } else {
    s = selStart.value
    e = selEnd.value
  }
  body.value = body.value.slice(0, s) + text + body.value.slice(e)
  nextTick(() => {
    if (el) {
      el.focus()
      const pos = s + text.length
      el.selectionStart = el.selectionEnd = pos
    }
  })
}

function wrapSelection(before: string, after = before) {
  const el = textarea.value
  if (!el) return
  const s = el.selectionStart
  const e = el.selectionEnd
  const sel = body.value.slice(s, e)
  body.value = body.value.slice(0, s) + before + sel + after + body.value.slice(e)
  nextTick(() => {
    el.focus()
    el.selectionStart = s + before.length
    el.selectionEnd = e + before.length
  })
}

function prefixLines(prefix: string) {
  const el = textarea.value
  if (!el) return
  const s = el.selectionStart
  const lineStart = body.value.lastIndexOf('\n', s - 1) + 1
  body.value = body.value.slice(0, lineStart) + prefix + body.value.slice(lineStart)
  nextTick(() => el.focus())
}

// ── Drag-and-drop / paste: image embedding + table insertion ──
const showTable = ref(false)
const tableHover = ref({ rows: 0, cols: 0 })

async function embedImageFile(file: File) {
  if (!file.type.startsWith('image/')) return
  try {
    const media = await notesApi.uploadMedia(props.note.id, file)
    const url = notesApi.mediaFileUrl(props.note.id, media.id)
    const alt = file.name.replace(/\.[^.]+$/, '') || 'image'
    applyText(`![${alt}](${url})`)
    showPreview.value = true // auto-preview so the embedded image is visible
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Image upload failed')
  }
}

async function embedCsvFile(file: File) {
  const md = delimitedToMarkdown(await file.text())
  if (md) applyText('\n' + md + '\n')
}

// ── Tauri native drag-drop ──
// WebKitGTK (the Tauri Linux webview) does not deliver HTML5 file drops, so in
// the desktop build we use Tauri's drag-drop event, which yields file *paths*.
// We import each path via the backend (avoids frontend fs-scope restrictions).
const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'svg']
let unlistenDrag: (() => void) | null = null

async function handleDroppedPaths(paths: string[]) {
  textarea.value?.focus()
  for (const path of paths) {
    const name = path.split(/[\\/]/).pop() || path
    const ext = name.split('.').pop()?.toLowerCase() ?? ''
    if (!IMAGE_EXTS.includes(ext)) continue
    try {
      const media = await notesApi.uploadMediaFromPath(props.note.id, path)
      const url = notesApi.mediaFileUrl(props.note.id, media.id)
      applyText(`![${name.replace(/\.[^.]+$/, '') || 'image'}](${url})`)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Image import failed')
    }
  }
  if (paths.length) showPreview.value = true // auto-preview so embedded images are visible
}

onMounted(async () => {
  if (!isTauri) return
  try {
    const { getCurrentWebview } = await import('@tauri-apps/api/webview')
    unlistenDrag = await getCurrentWebview().onDragDropEvent((event: any) => {
      const p = event?.payload
      if (!p) return
      if (p.type === 'enter' || p.type === 'over') isDragging.value = true
      else if (p.type === 'leave') isDragging.value = false
      else if (p.type === 'drop') {
        isDragging.value = false
        void handleDroppedPaths((p.paths as string[]) ?? [])
      }
    })
  } catch (e) {
    console.warn('Tauri drag-drop unavailable', e)
  }
})
onUnmounted(() => {
  unlistenDrag?.()
  unlistenDrag = null
})

async function onDropFiles(e: DragEvent) {
  // useDragDrop preventDefaults + filters to accepted file types + manages state.
  const accepted = dragHandlers.onDrop(e)
  if (!accepted?.length) return
  textarea.value?.focus()
  for (const f of accepted) {
    if (f.type.startsWith('image/')) await embedImageFile(f)
    else if (/\.csv$/i.test(f.name) || f.type === 'text/csv') await embedCsvFile(f)
  }
}

async function onPaste(e: ClipboardEvent) {
  if (isTauri) {
    await onPasteTauri(e)
    return
  }
  const cd = e.clipboardData
  if (!cd) return
  // 1) pasted image files → upload + embed
  const images: File[] = []
  for (const it of cd.items) {
    if (it.kind === 'file' && it.type.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) images.push(f)
    }
  }
  if (images.length) {
    e.preventDefault()
    for (const f of images) await embedImageFile(f)
    return
  }
  // 2) pasted HTML table → markdown table
  const html = cd.getData('text/html')
  if (html && /<table[\s>]/i.test(html)) {
    const md = htmlTableToMarkdown(html)
    if (md) {
      e.preventDefault()
      applyText('\n' + md + '\n')
      return
    }
  }
  // 3) pasted TSV/CSV text → markdown table
  const text = cd.getData('text/plain')
  if (text && text.includes('\n') && (text.includes('\t') || /^[^\n]*,[^\n]*\n/m.test(text))) {
    const md = delimitedToMarkdown(text)
    if (md) {
      e.preventDefault()
      applyText('\n' + md + '\n')
    }
  }
}

// Tauri paste: WebKitGTK doesn't expose pasted images via clipboardData, so we
// read the clipboard via the clipboard-manager plugin and encode it to PNG.
async function onPasteTauri(e: ClipboardEvent) {
  const cd = e.clipboardData
  // If the webview did expose an image, use it directly.
  const cdImage = cd
    ? Array.from(cd.items).find((it) => it.kind === 'file' && it.type.startsWith('image/'))
    : null
  if (cdImage) {
    e.preventDefault()
    const f = cdImage.getAsFile()
    if (f) await embedImageFile(f)
    return
  }
  // Otherwise try the system clipboard via Tauri.
  e.preventDefault()
  try {
    const { readImage } = await import('@tauri-apps/plugin-clipboard-manager')
    const img = await readImage()
    if (img) {
      await uploadClipImage(img)
      return
    }
  } catch {
    /* clipboard has no image */
  }
  // No image — restore the text the user pasted.
  const text = cd?.getData('text/plain') ?? ''
  if (text) applyText(text)
}

async function uploadClipImage(img: {
  rgba: () => Promise<Uint8Array>
  size: () => Promise<{ width: number; height: number }>
}) {
  const rgba = await img.rgba()
  const { width, height } = await img.size()
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const imgData = ctx.createImageData(width, height)
  imgData.data.set(rgba)
  ctx.putImageData(imgData, 0, 0)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob((b) => resolve(b), 'image/png')
  )
  if (!blob) return
  await embedImageFile(new File([blob], 'pasted.png', { type: 'image/png' }))
}

function insertTable(rows: number, cols: number) {
  const header = `| ${Array.from({ length: cols }, (_, i) => `Col ${i + 1}`).join(' | ')} |`
  const sep = `| ${Array.from({ length: cols }, () => '---').join(' | ')} |`
  const blank = `| ${Array.from({ length: cols }, () => '').join(' | ')} |`
  const bodyRows = Math.max(1, rows - 1)
  applyText('\n' + [header, sep, ...Array.from({ length: bodyRows }, () => blank)].join('\n') + '\n')
  showTable.value = false
}

function htmlTableToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return ''
  const grid = Array.from(table.querySelectorAll('tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td,th')).map(
      (c) => (c.textContent || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' ')
    )
  )
  return gridToMarkdown(grid)
}

function delimitedToMarkdown(text: string): string {
  const lines = text.replace(/\r/g, '').split('\n').filter((l) => l.length > 0)
  if (lines.length < 2) return ''
  const delim = lines[0].includes('\t') ? '\t' : ','
  return gridToMarkdown(lines.map((l) => l.split(delim)))
}

function gridToMarkdown(grid: string[][]): string {
  if (!grid.length || !grid[0]?.length) return ''
  const cols = Math.max(...grid.map((r) => r.length))
  const norm = grid.map((r) => {
    const row = [...r]
    while (row.length < cols) row.push('')
    return row.map((c) => c.trim().replace(/\|/g, '\\|'))
  })
  const line = (cells: string[]) => `| ${cells.join(' | ')} |`
  return [line(norm[0]), `| ${norm[0].map(() => '---').join(' | ')} |`, ...norm.slice(1).map(line)].join('\n')
}

// ── Note-level actions (immediate, not debounced) ──
async function togglePin() {
  await store.togglePin(props.note.id, !props.note.is_pinned)
}

async function changeFolder(value: string) {
  if (!value) return // "None" is disallowed — folders are required
  await store.updateNote(props.note.id, { folder_id: Number(value) })
}

async function toggleTag(id: number) {
  const current = props.note.tags.map((t) => t.id)
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
  await store.updateNote(props.note.id, { tag_ids: next })
}

async function onEncryptionChange() {
  // Body changed between plain/ciphertext on the server — reload + resync.
  await store.selectNote(props.note.id)
  const fresh = store.currentNote
  if (fresh) {
    body.value = fresh.body
    title.value = fresh.title ?? ''
  }
}

async function deleteNote() {
  if (!confirm('Delete this note? It can be restored later.')) return
  await store.deleteNote(props.note.id)
  emit('deleted')
}

// ── Misc ──
const { renderedPreview } = useMarkdownPreview(() => body.value, () => showPreview.value)

const wordCount = computed(() => {
  const t = body.value.trim()
  return t ? t.split(/\s+/).length : 0
})

const filteredTags = computed(() => {
  const q = tagQuery.value.trim().toLowerCase()
  if (!q) return props.allTags
  return props.allTags.filter((t) => t.name.toLowerCase().includes(q))
})

function isSelected(id: number) {
  return props.note.tags.some((t) => t.id === id)
}

function closeTags() {
  showTags.value = false
  tagQuery.value = ''
}

const canCreateTag = computed(() => {
  const q = tagQuery.value.trim()
  if (!q) return false
  return !props.allTags.some((t) => t.name.toLowerCase() === q.toLowerCase())
})

async function createAndAssignTag() {
  const name = tagQuery.value.trim()
  if (!name) return
  try {
    const tag = await tagsApi.create({ name })
    emit('tag-created') // parent refreshes the tag list
    const current = props.note.tags.map((t) => t.id)
    await store.updateNote(props.note.id, { tag_ids: [...current, tag.id] })
    tagQuery.value = ''
  } catch {
    /* store surfaces error */
  }
}

const saveLabel = computed(() => {
  if (saving.value) return 'Saving…'
  if (savedAt.value) return 'Saved'
  return ''
})
</script>

<template>
  <div
    class="relative flex flex-col h-full bg-surface"
    @dragenter="dragHandlers.onDragenter"
    @dragover="dragHandlers.onDragover"
    @dragleave="dragHandlers.onDragleave"
    @drop="onDropFiles"
  >
    <!-- Drop overlay (feedback that the editor accepts file drops) -->
    <div
      v-if="isDragging"
      class="absolute inset-0 z-50 flex items-center justify-center bg-accent/10 border-2 border-dashed border-accent rounded pointer-events-none"
    >
      <span class="text-accent text-sm font-medium">Drop image or .csv to embed</span>
    </div>
    <!-- Header: title + actions -->
    <div class="flex items-center gap-1.5 px-3 py-2 border-b border-border">
      <input
        v-model="title"
        placeholder="Untitled note"
        class="flex-1 bg-transparent text-sm font-semibold text-text-primary outline-none placeholder:text-text-muted"
        :disabled="note.is_encrypted"
      />
      <button
        @click="togglePin"
        class="p-1.5 rounded hover:bg-surface-hover transition-colors"
        :class="note.is_pinned ? 'text-accent' : 'text-text-secondary'"
        title="Pin note"
      >
        <Pin :size="16" />
      </button>
      <NoteEncryptionBadge
        :note-id="note.id"
        :is-encrypted="note.is_encrypted"
        @change="onEncryptionChange"
      />
      <button
        @click="deleteNote"
        class="p-1.5 rounded text-text-secondary hover:text-red-400 hover:bg-surface-hover transition-colors"
        title="Delete note"
      >
        <Trash2 :size="16" />
      </button>
    </div>

    <!-- Formatting toolbar -->
    <div class="flex items-center gap-0.5 px-2 py-1 border-b border-border bg-editor/40 flex-wrap">
      <button class="tb" title="Bold" @click="wrapSelection('**')"><Bold :size="13" /></button>
      <button class="tb" title="Italic" @click="wrapSelection('*')"><Italic :size="13" /></button>
      <span class="sep" />
      <button class="tb" title="Heading 1" @click="prefixLines('# ')"><Heading1 :size="13" /></button>
      <button class="tb" title="Heading 2" @click="prefixLines('## ')"><Heading2 :size="13" /></button>
      <button class="tb" title="Bullet list" @click="prefixLines('- ')"><List :size="13" /></button>
      <button class="tb" title="Quote" @click="prefixLines('> ')"><Quote :size="13" /></button>
      <button class="tb" title="Link" @click="wrapSelection('[', '](url)')"><LinkIcon :size="13" /></button>
      <div class="relative">
        <button
          class="tb"
          :class="showTable ? 'text-accent' : ''"
          title="Insert table"
          @click="showTable = !showTable"
        >
          <Table :size="13" />
        </button>
        <div v-if="showTable" class="fixed inset-0 z-30" @click="showTable = false" />
        <div
          v-if="showTable"
          class="absolute top-7 left-0 z-40 bg-surface border border-border rounded-lg shadow-xl p-2"
          @mouseleave="tableHover = { rows: 0, cols: 0 }"
        >
          <div v-for="r in 5" :key="r" class="flex gap-0.5">
            <button
              v-for="c in 5"
              :key="c"
              class="w-5 h-5 rounded transition-colors"
              :class="r <= tableHover.rows && c <= tableHover.cols ? 'bg-accent' : 'bg-surface-hover hover:bg-accent/40'"
              @mouseenter="tableHover = { rows: r, cols: c }"
              @click="insertTable(r, c)"
            />
          </div>
          <div class="text-[9px] text-text-muted text-center mt-1">
            {{ tableHover.rows }} × {{ tableHover.cols }}
          </div>
        </div>
      </div>
      <span class="sep" />
      <button
        class="tb"
        :class="showPreview ? 'text-accent' : ''"
        title="Toggle preview"
        @click="showPreview = !showPreview"
      >
        <Eye v-if="!showPreview" :size="13" />
        <Pencil v-else :size="13" />
      </button>
      <button
        class="tb"
        :class="showAi ? 'text-accent' : ''"
        title="AI tools"
        @click="showAi = !showAi"
      >
        <Sparkles :size="13" />
      </button>
      <span class="flex-1" />
      <span class="text-[10px] text-text-muted flex items-center gap-1">
        <Loader v-if="saving" :size="10" class="animate-spin" />
        {{ saveLabel }}
      </span>
    </div>

    <!-- Encrypted notice -->
    <div
      v-if="note.is_encrypted"
      class="px-3 py-6 text-center text-xs text-text-muted"
    >
      🔒 This note is encrypted. Decrypt it (lock icon above) to read and edit.
    </div>

    <!-- Editor / Preview -->
    <div v-else class="flex-1 overflow-hidden">
      <textarea
        v-show="!showPreview"
        ref="textarea"
        v-model="body"
        @keyup="updateSelection"
        @mouseup="updateSelection"
        @select="updateSelection"
        @paste="onPaste"
        class="w-full h-full resize-none bg-transparent px-4 py-3 text-sm text-text-primary outline-none custom-scrollbar"
        style="font-family: var(--editor-font); font-size: var(--editor-font-size)"
        placeholder="Start writing…"
      />
      <div
        v-show="showPreview"
        class="h-full overflow-y-auto custom-scrollbar px-4 py-3 md-body text-sm text-text-primary"
        v-html="renderedPreview"
      />
    </div>

    <!-- Meta footer: folder + tags + word count (single row) -->
    <div class="px-3 py-2 border-t border-border bg-editor/30">
      <div class="flex items-center gap-2">
        <!-- Folder (required: no "None" option) -->
        <span class="text-[10px] uppercase tracking-wider text-text-muted shrink-0">Folder</span>
        <select
          :value="note.folder_id == null ? '' : note.folder_id"
          @change="changeFolder(($event.target as HTMLSelectElement).value)"
          class="bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[11px] text-text-primary outline-none max-w-[8rem]"
        >
          <option value="" disabled>Select folder…</option>
          <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.name }}</option>
        </select>

        <!-- Tags dropdown -->
        <div class="relative shrink-0">
          <button
            @click="showTags = !showTags"
            class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-surface-hover text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
          >
            <Hash :size="10" />
            {{ note.tags.length ? `Tags (${note.tags.length})` : 'Add tags' }}
            <ChevronDown :size="10" />
          </button>

          <!-- Click-away backdrop -->
          <div v-if="showTags" class="fixed inset-0 z-30" @click="closeTags" />

          <!-- Dropdown panel (opens upward) -->
          <div
            v-if="showTags"
            class="absolute bottom-full left-0 mb-1 w-56 bg-surface border border-border rounded-lg shadow-xl z-40 overflow-hidden"
          >
            <div class="p-1.5 border-b border-border">
              <input
                v-model="tagQuery"
                placeholder="Filter or create tag…"
                class="w-full px-2 py-1 bg-surface-hover border border-border rounded text-[11px] text-text-primary outline-none focus:border-accent"
              />
            </div>
            <div class="max-h-52 overflow-y-auto custom-scrollbar p-1">
              <button
                v-for="t in filteredTags"
                :key="t.id"
                @click="toggleTag(t.id)"
                class="w-full flex items-center gap-2 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors"
                :class="isSelected(t.id) ? 'bg-accent/15 text-accent' : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'"
              >
                <Check v-if="isSelected(t.id)" :size="11" class="shrink-0" />
                <span v-else class="w-[11px] shrink-0" />
                <span class="truncate">#{{ t.name }}</span>
              </button>
              <div
                v-if="!filteredTags.length && !canCreateTag"
                class="px-2 py-3 text-center text-[10px] text-text-muted"
              >
                No matching tags
              </div>
            </div>
            <!-- Create new tag -->
            <button
              v-if="canCreateTag"
              @click="createAndAssignTag"
              class="w-full flex items-center gap-2 px-2 py-1.5 border-t border-border text-[11px] text-accent hover:bg-accent/10 cursor-pointer transition-colors"
            >
              <Plus :size="11" />
              Create <span class="font-medium truncate">{{ tagQuery.trim() }}</span>
            </button>
          </div>
        </div>

        <span class="flex-1" />
        <span class="text-[10px] text-text-muted shrink-0">{{ wordCount }} words</span>
      </div>
    </div>

    <!-- AI tools overlay -->
    <div
      v-if="showAi"
      class="absolute right-2 top-14 bottom-14 w-72 z-40 rounded-lg border border-border bg-surface shadow-xl overflow-hidden flex flex-col"
    >
      <div class="flex items-center justify-between px-2 py-1 border-b border-border">
        <span class="text-[10px] font-bold uppercase tracking-wider text-text-muted">AI Tools</span>
        <button @click="showAi = false" class="text-text-muted hover:text-text-primary text-xs">✕</button>
      </div>
      <div class="flex-1 overflow-hidden">
        <AiDrawerPanel
          :get-selection="getSelection"
          :apply-text="applyText"
          :has-entry="true"
          :entry-id="note.id"
          @close="showAi = false"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tb {
  padding: 0.25rem;
  border-radius: 0.25rem;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.tb:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.sep {
  width: 1px;
  height: 16px;
  background: var(--color-border);
  margin: 0 2px;
}
</style>
