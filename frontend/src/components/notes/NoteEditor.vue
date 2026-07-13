<script setup lang="ts">
import { ref, watch, computed, nextTick, onMounted, onUnmounted } from 'vue'
import {
  Eye, Pencil, Sparkles, Pin, Trash2, Loader, Volume2, Plus, X,
  ChevronUp, ChevronDown,
} from 'lucide-vue-next'
import { useMarkdownPreview } from '../../composables/useMarkdownPreview'
import { useDragDrop } from '../../composables/useDragDrop'
import { useRichTextEditor } from '../../composables/useRichTextEditor'
import { useLocalStorage } from '@vueuse/core'
import AiDrawerPanel from '../entry/AiDrawerPanel.vue'
import EditorToolbar from '../editor/EditorToolbar.vue'
import EditorContextMenu from '../editor/EditorContextMenu.vue'
import NoteEncryptionBadge from './NoteEncryptionBadge.vue'
import { useNotesStore } from '../../stores/notes'
import { tagsApi } from '../../api/tags'
import { notesApi } from '../../api/notes'
import { isTauri } from '../../api/client'
import { useTtsStore } from '../../stores/tts'
import type { NoteResponse, NoteFolderResponse, TagResponse, NotePageResponse } from '../../types'

const props = defineProps<{
  note: NoteResponse
  folders: NoteFolderResponse[]
  allTags: TagResponse[]
}>()
const emit = defineEmits<{ deleted: []; 'tag-created': []; 'new-note': [] }>()

const store = useNotesStore()
const tts = useTtsStore()
const { isDragging, handlers: dragHandlers } = useDragDrop()

// ── Page tabs ────────────────────────────────────────────────────────────────
// null = the "Main" tab (the note's own title/body, encrypted + FTS-backed).
// Otherwise the id of a NotePage row.
const activePageId = ref<number | null>(null)
const activePage = computed(
  () => props.note.pages.find((p) => p.id === activePageId.value) ?? null,
)
const isMain = computed(() => activePageId.value === null)

// ── Local editable buffers (resynced on note/page identity change only, so
//    our own autosave responses don't clobber in-flight typing) ──
const title = ref('')
const body = ref('')
const showPreview = ref(false)
const showAi = ref(false)
const showTags = ref(false)
const tagQuery = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
// ── Shared editing core (selection, formatting, history, AI, shortcuts) ──
const core = useRichTextEditor({ body, textarea, onSave: saveNow })
// Notes' embed / emoji / paste insert at the selection via the core.
const applyText = core.applyToSelection
const saving = ref(false)
const savedAt = ref<number | null>(null)
let saveTimer: ReturnType<typeof setTimeout> | null = null

function syncFromActive() {
  if (activePage.value) {
    title.value = activePage.value.title ?? ''
    body.value = activePage.value.body
  } else {
    title.value = props.note.title ?? ''
    body.value = props.note.body
  }
  // Fresh undo stack per source — undo never crosses a note/page boundary.
  core.resetHistory()
}

// Resync when the note changes or the active page changes. If the active page
// no longer belongs to this note (note switch / deletion), fall back to Main.
watch(
  [() => props.note.id, activePageId],
  () => {
    if (
      activePageId.value !== null &&
      !props.note.pages.some((p) => p.id === activePageId.value)
    ) {
      activePageId.value = null
      return
    }
    syncFromActive()
    // Pre-warm read-aloud for the opened source (skip encrypted main — body is ciphertext).
    if (!(isMain.value && props.note.is_encrypted)) tts.prewarmText(ttsText.value)
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  },
  { immediate: true },
)

// Debounced autosave for the active source.
watch([title, body], () => {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(doSave, 900)
})

async function doSave() {
  if (isMain.value) {
    if (title.value === (props.note.title ?? '') && body.value === props.note.body) return
    saving.value = true
    try {
      await store.updateNote(props.note.id, { title: title.value, body: body.value })
      savedAt.value = Date.now()
      if (!props.note.is_encrypted) tts.prewarmText(ttsText.value)
    } catch {
      /* store surfaces error */
    } finally {
      saving.value = false
    }
  } else {
    const p = activePage.value
    if (!p) return
    if (title.value === (p.title ?? '') && body.value === p.body) return
    saving.value = true
    try {
      await store.updatePage(p.id, { title: title.value, body: body.value })
      savedAt.value = Date.now()
    } catch {
      /* store surfaces error */
    } finally {
      saving.value = false
    }
  }
}

async function saveNow() {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  await doSave()
}

async function selectPage(id: number | null) {
  // Flush any pending edits on the outgoing source before switching.
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
    await doSave()
  }
  activePageId.value = id
}

// ── Page CRUD ────────────────────────────────────────────────────────────────
async function addPage() {
  await saveNow()
  const p = await store.createPage({ title: '', body: '' })
  if (p) activePageId.value = p.id
}

async function removePage(id: number) {
  if (!confirm('Delete this page?')) return
  const wasActive = activePageId.value === id
  await store.deletePage(id)
  if (wasActive) activePageId.value = null
}

// Inline rename of a page tab (double-click).
const editingPageId = ref<number | null>(null)
const editingTitle = ref('')
const vFocus = { mounted: (el: HTMLInputElement) => el.focus() }
function startRename(p: NotePageResponse) {
  editingPageId.value = p.id
  editingTitle.value = p.title ?? ''
}
async function commitRename() {
  const id = editingPageId.value
  editingPageId.value = null
  if (id != null && editingTitle.value.trim() !== '') {
    await store.updatePage(id, { title: editingTitle.value })
  }
}

// Drag reorder of page tabs.
let dragPageId: number | null = null
function onPageDragStart(e: DragEvent, id: number) {
  dragPageId = id
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function onPageDrop(e: DragEvent, targetId: number) {
  e.preventDefault()
  const fromId = dragPageId
  dragPageId = null
  if (fromId == null || fromId === targetId) return
  const reordered = props.note.pages.map((p) => p.id)
  const from = reordered.indexOf(fromId)
  const to = reordered.indexOf(targetId)
  if (from < 0 || to < 0) return
  const [moved] = reordered.splice(from, 1)
  reordered.splice(to, 0, moved)
  void store.reorderPages(reordered.map((id, i) => ({ id, sort_order: i })))
}

// ── Read aloud (drives the shared tts store; voice set in Settings → Features) ──
function stripMarkdown(s: string): string {
  return s
    .replace(/<audio[\s\S]*?<\/audio>/gi, ' ')
    .replace(/<video[\s\S]*?<\/video>/gi, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*_~`>-]/g, ' ')
    .replace(/\|/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
const ttsText = computed(() => stripMarkdown(body.value))
const speaking = computed(() => tts.isPlayingText(ttsText.value))
const ttsLoading = computed(() => tts.isLoadingText(ttsText.value))
async function toggleSpeak() {
  if (!ttsText.value) return
  try {
    await tts.toggleText(ttsText.value)
  } catch (e: unknown) {
    alert(`Read aloud failed: ${e instanceof Error ? e.message : e}`)
  }
}

// ── Notes toolbar state (font/size drive inline <span> injection) ──
const ribbonExpanded = useLocalStorage<boolean>('lifelogr-notes-ribbon-expanded', true)
const selFont = ref('')
const selSize = ref<number | ''>('')

// The shared toolbar emits font/size changes; wrap the selection in a span.
function onFontChange(v: string) {
  selFont.value = v
  if (v) core.wrapFont(v)
}
function onSizeChange(v: number | '') {
  selSize.value = v
  if (v !== '') core.wrapSize(v)
}

// ── Emoji picker ─────────────────────────────────────────────────────────────
const showEmoji = ref(false)
const EMOJI = [
  '😀','😁','😂','🤣','😊','😍','😘','😎','🤔','😴','🙄','😱',
  '👍','👎','👏','🙏','💪','✌️','🤝','👋','👌','✋',
  '❤️','🔥','✨','⭐','💯','🎉','🎊','🎁','💡','⚡',
  '✅','❌','⚠️','❓','❗','📌','📍','📎','🔗','🎯',
  '☀️','🌙','☕','🍕','🍔','🍰','🍺','⚽','🏀','🎵',
  '🚀','💻','📱','📷','🏠','✈️','🌱','🌈','🏆','💎',
]
function insertEmoji(e: string) {
  applyText(e)
  showEmoji.value = false
}

// ── Media embed (image / audio / video) ──────────────────────────────────────
const fileInput = ref<HTMLInputElement | null>(null)

function triggerInsert(kind: 'image' | 'audio' | 'video') {
  if (fileInput.value) {
    fileInput.value.accept =
      kind === 'image' ? 'image/*' : kind === 'audio' ? 'audio/*' : 'video/*'
    fileInput.value.value = ''
    fileInput.value.click()
  }
}
async function onFilePicked(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) await embedFile(f)
}
async function embedFile(file: File) {
  const t = file.type
  try {
    const media = await notesApi.uploadMedia(props.note.id, file)
    const url = notesApi.mediaFileUrl(props.note.id, media.id)
    const name = file.name.replace(/\.[^.]+$/, '') || 'media'
    if (t.startsWith('image/')) {
      applyText(`![${name}](${url})`)
      showPreview.value = true
    } else if (t.startsWith('audio/')) {
      applyText(`\n<audio controls preload="metadata" src="${url}"></audio>\n`)
    } else if (t.startsWith('video/')) {
      applyText(`\n<video controls preload="metadata" src="${url}" style="max-width:100%"></video>\n`)
    } else {
      applyText(`[${name}](${url})`)
    }
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Media upload failed')
  }
}

// ── Tauri native drag-drop (image import from file paths) ────────────────────
const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'svg']
const AUDIO_EXTS = ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'opus']
const VIDEO_EXTS = ['mp4', 'webm', 'mov', 'mkv', 'avi']
let unlistenDrag: (() => void) | null = null

async function handleDroppedPaths(paths: string[]) {
  textarea.value?.focus()
  for (const path of paths) {
    const name = path.split(/[\\/]/).pop() || path
    const ext = name.split('.').pop()?.toLowerCase() ?? ''
    try {
      const media = await notesApi.uploadMediaFromPath(props.note.id, path)
      const url = notesApi.mediaFileUrl(props.note.id, media.id)
      const base = name.replace(/\.[^.]+$/, '') || 'media'
      if (IMAGE_EXTS.includes(ext)) applyText(`![${base}](${url})`)
      else if (AUDIO_EXTS.includes(ext)) applyText(`\n<audio controls src="${url}"></audio>\n`)
      else if (VIDEO_EXTS.includes(ext)) applyText(`\n<video controls src="${url}" style="max-width:100%"></video>\n`)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Media import failed')
    }
  }
  if (paths.length) showPreview.value = true
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
  // Stop read-aloud only if this note is what's currently playing (single global stream).
  if (speaking.value || ttsLoading.value) tts.stop()
})

async function onDropFiles(e: DragEvent) {
  const accepted = dragHandlers.onDrop(e)
  if (!accepted?.length) return
  textarea.value?.focus()
  for (const f of accepted) {
    if (f.type.startsWith('image/') || f.type.startsWith('audio/') || f.type.startsWith('video/')) {
      await embedFile(f)
    } else if (/\.csv$/i.test(f.name) || f.type === 'text/csv') {
      const md = delimitedToMarkdown(await f.text())
      if (md) applyText('\n' + md + '\n')
    }
  }
}

async function onPaste(e: ClipboardEvent) {
  if (isTauri) {
    await onPasteTauri(e)
    return
  }
  const cd = e.clipboardData
  if (!cd) return
  const media: File[] = []
  for (const it of cd.items) {
    if (it.kind === 'file' && (it.type.startsWith('image/') || it.type.startsWith('audio/') || it.type.startsWith('video/'))) {
      const f = it.getAsFile()
      if (f) media.push(f)
    }
  }
  if (media.length) {
    e.preventDefault()
    for (const f of media) await embedFile(f)
    return
  }
  const html = cd.getData('text/html')
  if (html && /<table[\s>]/i.test(html)) {
    const md = htmlTableToMarkdown(html)
    if (md) {
      e.preventDefault()
      applyText('\n' + md + '\n')
      return
    }
  }
  const text = cd.getData('text/plain')
  if (text && text.includes('\n') && (text.includes('\t') || /^[^\n]*,[^\n]*\n/m.test(text))) {
    const md = delimitedToMarkdown(text)
    if (md) {
      e.preventDefault()
      applyText('\n' + md + '\n')
    }
  }
}

async function onPasteTauri(e: ClipboardEvent) {
  const cd = e.clipboardData
  const cdImage = cd
    ? Array.from(cd.items).find((it) => it.kind === 'file' && it.type.startsWith('image/'))
    : null
  if (cdImage) {
    e.preventDefault()
    const f = cdImage.getAsFile()
    if (f) await embedFile(f)
    return
  }
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
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob((b) => resolve(b), 'image/png'))
  if (!blob) return
  await embedFile(new File([blob], 'pasted.png', { type: 'image/png' }))
}

// ── Paste-to-table helpers (table button itself comes from the shared toolbar) ─
function htmlTableToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return ''
  const grid = Array.from(table.querySelectorAll('tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td,th')).map(
      (c) => (c.textContent || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' '),
    ),
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

// ── Note-level actions ───────────────────────────────────────────────────────
async function togglePin() {
  await store.togglePin(props.note.id, !props.note.is_pinned)
}
async function changeFolder(value: string) {
  if (!value) return
  await store.updateNote(props.note.id, { folder_id: Number(value) })
}
async function toggleTag(id: number) {
  const current = props.note.tags.map((t) => t.id)
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
  await store.updateNote(props.note.id, { tag_ids: next })
}
async function onEncryptionChange() {
  await store.selectNote(props.note.id)
  syncFromActive()
}
async function deleteNote() {
  if (!confirm('Delete this note? It can be restored later.')) return
  await store.deleteNote(props.note.id)
  emit('deleted')
}

// ── Tags ─────────────────────────────────────────────────────────────────────
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
    emit('tag-created')
    const current = props.note.tags.map((t) => t.id)
    await store.updateNote(props.note.id, { tag_ids: [...current, tag.id] })
    tagQuery.value = ''
  } catch {
    /* store surfaces error */
  }
}

// ── Resizable embedded media (preview) ───────────────────────────────────────
// Wrap each <img>/<video> in a drag-resizable span; the chosen size is remembered
// per src so it survives re-renders while editing.
const previewEl = ref<HTMLElement | null>(null)
const mediaSizes = useLocalStorage<Record<string, { w: number; h: number }>>(
  'lifelogr-note-media-sizes',
  {},
)
let mediaObservers: ResizeObserver[] = []
function disconnectMedia() {
  mediaObservers.forEach((o) => o.disconnect())
  mediaObservers = []
}
function wrapResizableMedia() {
  disconnectMedia()
  const root = previewEl.value
  if (!root) return
  root.querySelectorAll('img, video').forEach((node) => {
    const media = node as HTMLImageElement | HTMLVideoElement
    const parent = media.parentElement
    if (!parent) return
    const src = media.getAttribute('src') || ''
    const wrap = document.createElement('span')
    wrap.className = 'rmedia'
    parent.insertBefore(wrap, media)
    wrap.appendChild(media)
    media.style.width = '100%'
    media.style.height = '100%'
    media.style.display = 'block'
    const stored = mediaSizes.value[src]
    if (stored && stored.w) {
      wrap.style.width = stored.w + 'px'
      wrap.style.height = stored.h + 'px'
    }
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const cr = e.contentRect
        if (cr.width > 40 && cr.height > 40) {
          mediaSizes.value = {
            ...mediaSizes.value,
            [src]: { w: Math.round(cr.width), h: Math.round(cr.height) },
          }
        }
      }
    })
    ro.observe(wrap)
    mediaObservers.push(ro)
  })
}

// ── Right-click → shared AI context menu (selection + AI driven by the core) ──
const showContextMenu = ref(false)
const contextMenuPos = ref({ x: 0, y: 0 })
function onContextMenu(e: MouseEvent) {
  if (!core.getSelection().trim()) return // no selection → let the native menu show
  e.preventDefault()
  core.cacheSelection()
  const maxLeft = (typeof window !== 'undefined' ? window.innerWidth : 9999) - 240
  contextMenuPos.value = { x: Math.min(e.clientX, Math.max(0, maxLeft)), y: e.clientY }
  showContextMenu.value = true
}
function copySelection() {
  const t = core.getSelectionRaw()
  if (t) navigator.clipboard.writeText(t)
}
function cutSelection() {
  const t = core.getSelectionRaw()
  if (t) {
    navigator.clipboard.writeText(t)
    core.applyToSelection('')
  }
}
/** Route a toolbar action: embed uploads are notes-local; everything else is core. */
function onToolbarAction(name: string) {
  if (name === 'embedImage') return triggerInsert('image')
  if (name === 'embedAudio') return triggerInsert('audio')
  if (name === 'embedVideo') return triggerInsert('video')
  const fn = (core.actions as any)[name]
  if (fn) fn()
}

// Re-wrap embedded media as resizable nodes whenever the preview renders.
watch(
  [renderedPreview, showPreview],
  () => {
    if (showPreview.value) nextTick(wrapResizableMedia)
  },
)
onUnmounted(() => {
  disconnectMedia()
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
    <input ref="fileInput" type="file" class="hidden" @change="onFilePicked" />

    <!-- Drop overlay -->
    <div
      v-if="isDragging"
      class="absolute inset-0 z-50 flex items-center justify-center bg-accent/10 border-2 border-dashed border-accent rounded pointer-events-none"
    >
      <span class="text-accent text-sm font-medium">Drop image / audio / video to embed</span>
    </div>

    <!-- Title row -->
    <div class="flex items-center gap-1.5 px-3 py-2 border-b border-border">
      <span class="shrink-0 text-[10px] font-bold uppercase tracking-wider text-text-muted">
        {{ isMain ? 'Note' : 'Page' }}
      </span>
      <input
        v-model="title"
        :placeholder="isMain ? 'Untitled note' : 'Page title'"
        :disabled="isMain && note.is_encrypted"
        class="flex-1 bg-transparent text-sm font-semibold text-text-primary outline-none placeholder:text-text-muted disabled:opacity-70"
      />
      <button
        @click="togglePin"
        class="p-1.5 rounded hover:bg-surface-hover transition-colors"
        :class="note.is_pinned ? 'text-accent' : 'text-text-secondary'"
        title="Pin note"
      >
        <Pin :size="15" />
      </button>
    </div>

    <!-- Shared formatting toolbar (notes mode) — foldable -->
    <div class="ribbon-wrap relative">
      <div v-if="ribbonExpanded">
        <EditorToolbar
          mode="notes"
          :active-formats="core.activeFormats.value"
          :undo-count="core.undoStack.value.length"
          :redo-count="core.redoStack.value.length"
          :show-emoji="showEmoji"
          :show-find="core.showFind.value"
          :sel-font="selFont"
          :sel-size="selSize"
          @action="onToolbarAction"
          @toggle-emoji="showEmoji = !showEmoji"
          @toggle-find="core.showFind.value = !core.showFind.value"
          @change-font="(v: string) => onFontChange(v)"
          @change-size="(v: number | '') => onSizeChange(v)"
        />
        <div class="flex items-center justify-end px-2 py-0.5 border-t border-border/50">
          <button class="rbtn" title="Hide toolbar" @click="ribbonExpanded = false"><ChevronUp :size="13" /></button>
        </div>
        <!-- Emoji picker (notes-local popover) -->
        <div v-if="showEmoji" class="fixed inset-0 z-30" @click="showEmoji = false" />
        <div v-if="showEmoji" class="absolute right-2 top-full z-40 emoji-pop" @click.stop>
          <button v-for="e in EMOJI" :key="e" class="emoji-item" @click="insertEmoji(e)">{{ e }}</button>
        </div>
      </div>
      <button v-else class="ribbon-collapsed" title="Show formatting toolbar" @click="ribbonExpanded = true">
        <ChevronDown :size="13" /><span class="ml-1 text-[11px] text-text-muted">Formatting</span>
      </button>
    </div>

    <!-- Page tabs (EPIM-style leaves with CRUD) -->
    <div class="page-tabs">
      <button class="ptab" :class="{ active: isMain }" title="Main page" @click="selectPage(null)">
        <span class="truncate">{{ note.title?.trim() || 'Main' }}</span>
      </button>
      <div
        v-for="p in note.pages"
        :key="p.id"
        class="ptab"
        :class="{ active: activePageId === p.id }"
        draggable="true"
        title="Click to open · double-click to rename · drag to reorder"
        @click="selectPage(p.id)"
        @dblclick="startRename(p)"
        @dragstart="onPageDragStart($event, p.id)"
        @dragover.prevent
        @drop="onPageDrop($event, p.id)"
      >
        <input
          v-if="editingPageId === p.id"
          v-model="editingTitle"
          v-focus
          class="rename-input"
          @click.stop
          @blur="commitRename"
          @keydown.enter.prevent="commitRename"
          @keydown.esc.prevent="editingPageId = null"
        />
        <template v-else>
          <span class="truncate">{{ p.title?.trim() || 'Untitled' }}</span>
          <button class="ptab-x" title="Delete page" @click.stop="removePage(p.id)"><X :size="11" /></button>
        </template>
      </div>
      <button class="ptab ptab-add" title="Add page" @click="addPage"><Plus :size="13" /></button>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-hidden flex flex-col">
      <div
        v-if="isMain && note.is_encrypted"
        class="flex-1 flex items-center justify-center px-3 text-center text-xs text-text-muted"
      >
        🔒 This note is encrypted. Decrypt it (lock icon below) to read and edit.
      </div>
      <template v-else>
        <textarea
          v-show="!showPreview"
          ref="textarea"
          v-model="body"
          @input="core.onInput"
          @keydown="core.onTextareaKeydown"
          @keydown.capture="core.onShortcutKeydown"
          @keyup="core.cacheSelection"
          @mouseup="core.cacheSelection"
          @select="core.cacheSelection"
          @focus="core.clearSelCache"
          @blur="core.startSelCache"
          @paste="onPaste"
          @contextmenu="onContextMenu"
          class="flex-1 w-full resize-none bg-transparent px-4 py-3 text-sm text-text-primary outline-none custom-scrollbar"
          style="font-family: var(--editor-font); font-size: var(--editor-font-size)"
          placeholder="Start writing…"
        />
        <div
          v-show="showPreview"
          ref="previewEl"
          class="flex-1 overflow-y-auto custom-scrollbar px-4 py-3 md-body text-sm text-text-primary"
          v-html="renderedPreview"
        />
      </template>
    </div>

    <!-- Bottom action bar -->
    <div class="action-bar">
      <!-- Primary: Save + New (next to the tag selector on the right) -->
      <button class="actbtn save" :disabled="saving" title="Save now" @click="saveNow">
        <span>💾</span><span class="hidden sm:inline">{{ saving ? 'Saving' : 'Save' }}</span>
      </button>
      <button class="actbtn" title="New note" @click="emit('new-note')">
        <Plus :size="13" /><span class="hidden sm:inline">New</span>
      </button>
      <button
        class="actbtn"
        :class="{ 'text-accent': speaking }"
        :disabled="ttsLoading"
        :title="speaking ? 'Stop reading' : ttsLoading ? 'Generating audio…' : 'Read aloud (set voice in Settings → Features → Read Aloud)'"
        @click="toggleSpeak"
      >
        <Loader v-if="ttsLoading" :size="13" class="animate-spin" />
        <Volume2 v-else :size="13" /><span class="hidden md:inline">{{ speaking ? 'Stop' : 'Read' }}</span>
      </button>

      <span class="act-sep" />

      <button class="iconbtn" title="Delete note" @click="deleteNote"><Trash2 :size="13" /></button>
      <NoteEncryptionBadge
        :note-id="note.id"
        :is-encrypted="note.is_encrypted"
        @change="onEncryptionChange"
      />
      <button
        class="iconbtn"
        :class="{ 'text-accent': showPreview }"
        :title="showPreview ? 'Edit' : 'Preview'"
        @click="showPreview = !showPreview"
      >
        <Eye v-if="!showPreview" :size="13" /><Pencil v-else :size="13" />
      </button>
      <button class="iconbtn" :class="{ 'text-accent': showAi }" title="AI tools" @click="showAi = !showAi">
        <Sparkles :size="13" />
      </button>

      <span class="flex-1" />

      <!-- Folder -->
      <select
        :value="note.folder_id == null ? '' : note.folder_id"
        class="folder-sel"
        @change="changeFolder(($event.target as HTMLSelectElement).value)"
        title="Folder"
      >
        <option value="" disabled>Folder…</option>
        <option v-for="f in folders" :key="f.id" :value="f.id">{{ f.name }}</option>
      </select>

      <!-- Tags -->
      <div class="relative shrink-0">
        <button class="tagbtn" @click="showTags = !showTags">
          <span>#</span>{{ note.tags.length ? note.tags.length : 'Tags' }}
        </button>
        <div v-if="showTags" class="fixed inset-0 z-30" @click="closeTags" />
        <div v-if="showTags" class="absolute bottom-full right-0 mb-1 w-56 bg-surface border border-border rounded-lg shadow-xl z-40 overflow-hidden">
          <div class="p-1.5 border-b border-border">
            <input v-model="tagQuery" placeholder="Filter or create tag…" class="tag-filter" />
          </div>
          <div class="max-h-52 overflow-y-auto custom-scrollbar p-1">
            <button
              v-for="t in filteredTags"
              :key="t.id"
              class="tag-item"
              :class="isSelected(t.id) ? 'sel' : ''"
              @click="toggleTag(t.id)"
            >
              <span class="truncate">#{{ t.name }}</span>
            </button>
            <div v-if="!filteredTags.length && !canCreateTag" class="px-2 py-3 text-center text-[10px] text-text-muted">No matching tags</div>
          </div>
          <button v-if="canCreateTag" class="tag-create" @click="createAndAssignTag">
            <Plus :size="11" /> Create <span class="font-medium truncate">{{ tagQuery.trim() }}</span>
          </button>
        </div>
      </div>

      <span class="wc">
        <Loader v-if="saving" :size="10" class="animate-spin" />
        {{ saving ? '…' : savedAt ? `${wordCount}w ✓` : `${wordCount}w` }}
      </span>
    </div>

    <!-- Right-click → shared AI context menu (no encrypt item in notes) -->
    <EditorContextMenu
      :enable-encrypt="false"
      :visible="showContextMenu"
      :position="contextMenuPos"
      :ai-loading="core.aiLoading.value"
      :ai-result="core.aiResult.value"
      :ai-result-mode="core.aiResultMode.value"
      :ai-param-value="core.aiParamValue.value"
      :selected-text="core.getSelection()"
      @close="showContextMenu = false"
      @copy="copySelection"
      @cut="cutSelection"
      @bold="core.actions.bold()"
      @italic="core.actions.italic()"
      @run-ai-tool="(mode: string) => core.runAiTool(mode)"
      @open-ai-drawer="showAi = true"
      @ai-result-replace="core.aiResultReplace"
      @ai-result-insert="core.aiResultInsert"
      @ai-result-retry="core.aiResultRetry"
      @ai-result-copy="core.aiResultCopy"
      @apply-tool-param="(value: string) => core.applyToolParam(value)"
      @close-result="core.clearAiResult"
    />

    <!-- AI tools overlay -->
    <div
      v-if="showAi"
      class="absolute right-2 top-24 bottom-16 w-72 z-40 rounded-lg border border-border bg-surface shadow-xl overflow-hidden flex flex-col"
    >
      <div class="flex items-center justify-between px-2 py-1 border-b border-border">
        <span class="text-[10px] font-bold uppercase tracking-wider text-text-muted">AI Tools</span>
        <button class="text-text-muted hover:text-text-primary text-xs" @click="showAi = false">✕</button>
      </div>
      <div class="flex-1 overflow-hidden">
        <AiDrawerPanel
          :get-selection="core.getSelection"
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
/* ── Ribbon ────────────────────────────────────────────────────────────────── */
.ribbon {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-accent) 5%, var(--color-editor));
  flex-wrap: wrap;
}
.ribbon-wrap { border-bottom: 1px solid var(--color-border); }
.ribbon-collapsed {
  display: inline-flex;
  align-items: center;
  width: 100%;
  justify-content: center;
  padding: 0.3rem;
  color: var(--color-text-muted);
  cursor: pointer;
  background: color-mix(in srgb, var(--color-accent) 4%, var(--color-editor));
  transition: color 0.15s;
}
.ribbon-collapsed:hover { color: var(--color-accent); }
.ribbon-sel {
  height: 24px;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: 0.3rem;
  padding: 0 0.25rem;
  font-size: 11px;
  color: var(--color-text-secondary);
  outline: none;
  cursor: pointer;
}
.ribbon-sel:focus { border-color: var(--color-accent); }
.ribbon-sel-size { width: 3.2rem; }
.emoji-pop {
  position: absolute;
  top: 30px;
  right: 0;
  z-index: 40;
  width: 220px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  padding: 0.4rem;
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 0.15rem;
  max-height: 240px;
  overflow-y: auto;
}
.emoji-item {
  font-size: 16px;
  padding: 0.2rem;
  border-radius: 0.25rem;
  cursor: pointer;
  line-height: 1;
  transition: background-color 0.12s;
}
.emoji-item:hover { background: var(--color-surface-hover); }
.rgroup { display: flex; align-items: center; gap: 0.125rem; }
.rsep {
  width: 1px;
  height: 18px;
  background: var(--color-border);
  margin: 0 0.2rem;
}
.rbtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 0.35rem;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.rbtn:hover { background: var(--color-surface-hover); color: var(--color-text-primary); }

/* ── Page tabs ──────────────────────────────────────────────────────────────── */
.page-tabs {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-editor);
  overflow-x: auto;
}
.ptab {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: 150px;
  padding: 0.25rem 0.55rem;
  border-radius: 0.4rem 0.4rem 0 0;
  font-size: 11.5px;
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s, color 0.15s;
}
.ptab:hover { background: var(--color-surface-hover); color: var(--color-text-secondary); }
.ptab.active {
  color: var(--color-accent);
  background: var(--color-surface);
  border-color: var(--color-border);
  border-bottom-color: var(--color-surface);
  font-weight: 600;
  position: relative;
  top: 1px;
}
.ptab-add { color: var(--color-text-muted); padding: 0.25rem 0.4rem; }
.ptab-x {
  display: inline-flex;
  opacity: 0;
  color: var(--color-text-muted);
  transition: opacity 0.15s, color 0.15s;
}
.ptab:hover .ptab-x { opacity: 0.7; }
.ptab-x:hover { opacity: 1; color: var(--color-danger, #ef4444); }
.rename-input {
  width: 90px;
  padding: 0.05rem 0.25rem;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-accent);
  border-radius: 0.25rem;
  font-size: 11.5px;
  color: var(--color-text-primary);
  outline: none;
}

/* ── Bottom action bar ─────────────────────────────────────────────────────── */
.action-bar {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.6rem;
  border-top: 1px solid var(--color-border);
  background: var(--color-editor);
  flex-wrap: wrap;
}
.actbtn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.28rem 0.5rem;
  border-radius: 0.4rem;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.actbtn:hover { color: var(--color-text-primary); }
.actbtn.save { color: var(--color-accent); }
.actbtn.save:hover { background: color-mix(in srgb, var(--color-accent) 14%, transparent); }
.actbtn:disabled { opacity: 0.6; cursor: default; }
.act-sep { width: 1px; height: 18px; background: var(--color-border); margin: 0 0.15rem; }
.iconbtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 0.35rem;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.iconbtn:hover { background: var(--color-surface-hover); color: var(--color-text-primary); }
.folder-sel {
  max-width: 8rem;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: 0.35rem;
  padding: 0.2rem 0.35rem;
  font-size: 11px;
  color: var(--color-text-primary);
  outline: none;
}
.tagbtn {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  padding: 0.22rem 0.45rem;
  border-radius: 0.35rem;
  font-size: 11px;
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
  cursor: pointer;
  transition: color 0.15s;
}
.tagbtn:hover { color: var(--color-accent); }
.tag-filter {
  width: 100%;
  padding: 0.3rem 0.45rem;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: 0.3rem;
  font-size: 11px;
  color: var(--color-text-primary);
  outline: none;
}
.tag-filter:focus { border-color: var(--color-accent); }
.tag-item {
  width: 100%;
  text-align: left;
  padding: 0.3rem 0.45rem;
  border-radius: 0.3rem;
  font-size: 11px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s;
}
.tag-item:hover { background: var(--color-surface-hover); color: var(--color-text-primary); }
.tag-item.sel { color: var(--color-accent); }
.tag-create {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.35rem 0.5rem;
  border-top: 1px solid var(--color-border);
  font-size: 11px;
  color: var(--color-accent);
  cursor: pointer;
}
.tag-create:hover { background: color-mix(in srgb, var(--color-accent) 10%, transparent); }
.wc {
  font-size: 10px;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-variant-numeric: tabular-nums;
}

/* ── Resizable embedded media ── */
:deep(.rmedia) {
  display: inline-block;
  resize: both;
  overflow: hidden;
  max-width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 0.4rem;
  line-height: 0;
}
:deep(.rmedia > img),
:deep(.rmedia > video) {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
