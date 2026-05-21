<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useEntriesStore } from '../../stores/entries'
import { useTagsStore } from '../../stores/tags'
import { useUiStore } from '../../stores/ui'
import {
  X, Eye, Edit3, Bold, Italic, Strikethrough, Heading1, Heading2,
  List, ListOrdered, Quote, Code, Link, Image, Minus,
  Undo2, Redo2, Maximize2, Minimize2, Search, Type, AlignLeft,
  Table, CheckSquare, Clock, ChevronUp, ChevronDown,
  Sparkles, History, MapPin, Plus, Lock, Trash2, Tag, Mic, Volume2, Paperclip, Film, Music, FileText, LayoutTemplate,
  BarChart3, Search as SearchIcon, Lightbulb, Loader
} from 'lucide-vue-next'
import AiPanel from './AiPanel.vue'
import RevisionPanel from './RevisionPanel.vue'
import EncryptionBadge from './EncryptionBadge.vue'
import GeotagModal from './GeotagModal.vue'
import TagList from '../tags/TagList.vue'
import RecordingPanel from '../recordings/RecordingPanel.vue'
import MediaViewer from '../media/MediaViewer.vue'
import TemplatePicker from '../templates/TemplatePicker.vue'
import { setGeotag } from '../../api/geotagging'
import { aiStatus, suggestTags, getEntryAnalysis, findSimilar } from '../../api/ai'
import { ttsApi } from '../../api/tts'
import { mediaApi } from '../../api/media'
import { formatFileSize } from '../../composables/useFormat'
import { useLocalStorage } from '@vueuse/core'
import { marked } from 'marked'

marked.use({ gfm: true, breaks: true })
import DOMPurify from 'dompurify'
import type { MediaResponse, EntryAnalysisResponse, SimilarEntry } from '../../types'

const entries = useEntriesStore()
const ui = useUiStore()

const isNew = computed(() => ui.editingEntryId === -1)
const hasEntry = computed(() => ui.editingEntryId != null && ui.editingEntryId > 0)
const title = ref('')
const body = ref('')
const tagIds = ref<number[]>([])
const entryDate = ref('')
const showPreview = ref(false)
const fullscreen = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)
const showAi = ref(false)
const showRevisions = ref(false)
const showGeotag = ref(false)
const showRecording = ref(false)
const showAttachments = ref(false)
const showTemplates = ref(false)
const attachments = ref<MediaResponse[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const viewerOpen = ref(false)
const viewerIndex = ref(0)
const showTagDropdown = ref(false)
const aiAvailable = ref<boolean | null>(null)
const suggestedTags = ref<string[]>([])
const suggestingTags = ref(false)
const showAnalysis = ref(false)
const analysis = ref<EntryAnalysisResponse | null>(null)
const analysisLoading = ref(false)
const similarEntries = ref<SimilarEntry[]>([])
const similarLoading = ref(false)
const ttsPlaying = ref(false)
const ttsLoading = ref(false)
let ttsAudio: HTMLAudioElement | null = null
const isEncrypted = ref(false)
const pendingGeotag = ref<{ latitude: number; longitude: number; location_name: string | null } | null>(null)
const defaultTemplateId = useLocalStorage<number | null>('diarium-default-template', null)

function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e) }

// ── Dirty tracking ──
const dirty = ref(false)
const savedSnapshot = ref('')

function markDirty() { dirty.value = true; ui.editorIsDirty = true }

function snapshot() {
  savedSnapshot.value = JSON.stringify({ body: body.value, title: title.value, tagIds: tagIds.value })
  dirty.value = false
  ui.editorIsDirty = false
}

function isDirty(): boolean {
  if (dirty.value) return true
  const current = JSON.stringify({ body: body.value, title: title.value, tagIds: tagIds.value })
  return current !== savedSnapshot.value
}

// ── Undo / Redo history ──
interface HistoryEntry { content: string; cursor: number }
const undoStack = ref<HistoryEntry[]>([])
const redoStack = ref<HistoryEntry[]>([])
let lastPushTime = 0

function pushHistory() {
  const el = textarea.value
  const cursor = el ? el.selectionStart : 0
  const now = Date.now()
  // Debounce: don't push if < 500ms since last push and content is similar
  if (now - lastPushTime < 500 && undoStack.value.length > 0) {
    const last = undoStack.value[undoStack.value.length - 1]
    if (last.content === body.value) return
    // Update in place for rapid typing
    undoStack.value[undoStack.value.length - 1] = { content: body.value, cursor }
    return
  }
  lastPushTime = now
  undoStack.value.push({ content: body.value, cursor })
  if (undoStack.value.length > 200) undoStack.value.shift()
  redoStack.value = []
}

function doUndo() {
  if (undoStack.value.length < 2) return
  const current = undoStack.value.pop()!
  redoStack.value.push(current)
  const prev = undoStack.value[undoStack.value.length - 1]
  body.value = prev.content
  nextTick(() => {
    if (textarea.value) {
      textarea.value.selectionStart = textarea.value.selectionEnd = prev.cursor
    }
  })
}

function doRedo() {
  if (!redoStack.value.length) return
  const entry = redoStack.value.pop()!
  undoStack.value.push(entry)
  body.value = entry.content
  nextTick(() => {
    if (textarea.value) {
      textarea.value.selectionStart = textarea.value.selectionEnd = entry.cursor
    }
  })
}

// ── Find & Replace ──
const showFind = ref(false)
const findQuery = ref('')
const replaceQuery = ref('')
const findIndex = ref(-1)
const findCount = ref(0)

const findMatches = computed(() => {
  if (!findQuery.value) { findIndex.value = -1; findCount.value = 0; return [] }
  const matches: number[] = []
  const q = findQuery.value.toLowerCase()
  const txt = body.value.toLowerCase()
  let i = -1
  while ((i = txt.indexOf(q, i + 1)) !== -1) matches.push(i)
  findCount.value = matches.length
  return matches
})

function jumpToMatch(dir: 1 | -1 = 1) {
  if (!findMatches.value.length) { findIndex.value = -1; return }
  if (findIndex.value === -1) { findIndex.value = 0 }
  else { findIndex.value = (findIndex.value + dir + findMatches.value.length) % findMatches.value.length }
  const pos = findMatches.value[findIndex.value]
  nextTick(() => {
    if (!textarea.value) return
    textarea.value.focus()
    textarea.value.selectionStart = pos
    textarea.value.selectionEnd = pos + findQuery.value.length
  })
}

function replaceOne() {
  if (findIndex.value < 0 || !findMatches.value.length) return
  const pos = findMatches.value[findIndex.value]
  body.value = body.value.slice(0, pos) + replaceQuery.value + body.value.slice(pos + findQuery.value.length)
  pushHistory()
  nextTick(() => jumpToMatch(1))
}

function replaceAll() {
  if (!findQuery.value) return
  const q = findQuery.value
  body.value = body.value.split(q).join(replaceQuery.value)
  pushHistory()
  findIndex.value = -1
}

// ── Stats ──
const stats = computed(() => {
  const text = body.value
  const chars = text.length
  const words = text.trim() ? text.trim().split(/\s+/).length : 0
  const lines = text ? text.split('\n').length : 0
  const paragraphs = text.trim() ? text.trim().split(/\n\s*\n/).length : 0
  const readMins = Math.max(1, Math.ceil(words / 200))
  return { chars, words, lines, paragraphs, readMins }
})

// ── Toolbar formatting ──
function wrap(before: string, after: string, placeholder = '') {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = body.value.slice(start, end) || placeholder
  const replacement = before + selected + after
  body.value = body.value.slice(0, start) + replacement + body.value.slice(end)
  pushHistory()
  nextTick(() => {
    el.focus()
    el.selectionStart = start + before.length
    el.selectionEnd = start + before.length + selected.length
  })
}

function prependLine(prefix: string) {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart
  const lineStart = body.value.lastIndexOf('\n', start - 1) + 1
  body.value = body.value.slice(0, lineStart) + prefix + body.value.slice(lineStart)
  pushHistory()
  nextTick(() => {
    el.focus()
    el.selectionStart = el.selectionEnd = start + prefix.length
  })
}

function insertAtCursor(text: string) {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart
  body.value = body.value.slice(0, start) + text + body.value.slice(el.selectionEnd)
  pushHistory()
  nextTick(() => {
    el.focus()
    el.selectionStart = el.selectionEnd = start + text.length
  })
}

function insertTable() {
  insertAtCursor('\n| Header | Header |\n|--------|--------|\n| Cell   | Cell   |\n')
}

function insertCheckbox() {
  prependLine('- [ ] ')
}

const fmt = {
  bold: () => wrap('**', '**', 'bold text'),
  italic: () => wrap('*', '*', 'italic text'),
  strikethrough: () => wrap('~~', '~~', 'strikethrough'),
  h1: () => prependLine('# '),
  h2: () => prependLine('## '),
  ul: () => prependLine('- '),
  ol: () => prependLine('1. '),
  quote: () => prependLine('> '),
  code: () => wrap('`', '`', 'code'),
  codeBlock: () => wrap('\n```\n', '\n```\n', 'code block'),
  link: () => wrap('[', '](url)', 'link text'),
  image: () => wrap('![', '](url)', 'alt text'),
  hr: () => insertAtCursor('\n---\n'),
  table: insertTable,
  checkbox: insertCheckbox,
  undo: doUndo,
  redo: doRedo,
}

const renderedPreview = computed(() => DOMPurify.sanitize(marked(body.value) as string))

// ── Load entry data ──
async function loadEntry() {
  body.value = ''
  title.value = ''
  tagIds.value = []

  if (isNew.value) {
    if (ui.newEntryDate) {
      entryDate.value = ui.newEntryDate
    } else {
      const d = new Date()
      entryDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    }
    // Auto-apply default template
    if (defaultTemplateId.value) {
      try {
        const store = await import('../../stores/templates').then(m => m.useTemplatesStore())
        await store.fetchAll()
        const tmpl = store.templates.find(t => t.id === defaultTemplateId.value)
        if (tmpl) {
          body.value = tmpl.body
          title.value = tmpl.name
        }
      } catch { /* ignore */ }
    }
  } else if (ui.editingEntryId) {
    const entry = await entries.fetchEntry(ui.editingEntryId!)
    if (entry) {
      isEncrypted.value = entry.is_encrypted
      if (entry.is_encrypted) {
        body.value = ''
        title.value = entry.title ?? ''
      } else {
        body.value = entry.body
        title.value = entry.title ?? ''
      }
      tagIds.value = entry.tags.map(t => t.id)
      entryDate.value = entry.entry_date
    }
  }
  pushHistory()
  snapshot()
  loadAttachments()
}

onMounted(loadEntry)
watch([() => ui.editingEntryId, () => ui.newEntryDate], () => { loadEntry(); loadAttachments() })

// Check AI availability once
aiStatus().then(s => { aiAvailable.value = s.ollama_available && s.model_loaded }).catch(() => { aiAvailable.value = false })

async function onEncryptionChange(encrypted: boolean) {
  isEncrypted.value = encrypted
  await loadEntry()
}

let saveTimer: ReturnType<typeof setTimeout> | null = null

function onInput() {
  pushHistory()
  markDirty()
  if (isNew.value) return
  if (saveTimer) clearTimeout(saveTimer)
  if (!body.value.trim()) return
  saveTimer = setTimeout(() => {
    entries.updateEntry(ui.editingEntryId!, { title: title.value || null, body: body.value, tag_ids: tagIds.value })
  }, 2000)
}

// ── Keyboard shortcuts ──
function onKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey

  // Undo / Redo
  if (mod && e.key === 'z' && !e.shiftKey) { e.preventDefault(); doUndo(); return }
  if (mod && (e.key === 'y' || (e.key === 'z' && e.shiftKey) || (e.key === 'Z'))) { e.preventDefault(); doRedo(); return }

  // Save
  if (mod && e.key === 's') { e.preventDefault(); save(); return }

  // Find
  if (mod && e.key === 'f') { e.preventDefault(); showFind.value = true; return }
  if (e.key === 'Escape' && showFind.value) { showFind.value = false; return }
  if (e.key === 'Enter' && showFind.value && findQuery.value) { e.preventDefault(); jumpToMatch(e.shiftKey ? -1 : 1); return }

  // Formatting
  if (!mod) return
  const handlers: Record<string, () => void> = {
    b: fmt.bold,
    i: fmt.italic,
    k: fmt.code,
    u: fmt.strikethrough,
  }
  const handler = handlers[e.key.toLowerCase()]
  if (handler) {
    e.preventDefault()
    handler()
  }
}

function onTextareaKeydown(e: KeyboardEvent) {
  // Auto-indent on Enter: continue list prefixes
  if (e.key === 'Enter') {
    const el = textarea.value
    if (!el) return
    const pos = el.selectionStart
    const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
    const currentLine = body.value.slice(lineStart, pos)

    // Match list patterns
    const listMatch = currentLine.match(/^(\s*)([-*+]|\d+\.)\s/)
    const checkboxMatch = currentLine.match(/^(\s*)- \[[ x]\]\s/)

    if (listMatch || checkboxMatch) {
      e.preventDefault()
      const prefix = checkboxMatch ? checkboxMatch[1] + '- [ ] ' : listMatch![0]

      // If current line is empty (just prefix), clear it
      if (currentLine.trim() === listMatch?.[0]?.trim() || currentLine.trim() === checkboxMatch?.[0]?.trim()) {
        body.value = body.value.slice(0, lineStart) + body.value.slice(pos)
        nextTick(() => { el.selectionStart = el.selectionEnd = lineStart })
        return
      }

      // Increment numbered list
      let newPrefix = prefix
      const numMatch = prefix.match(/^(\s*)(\d+)\.\s/)
      if (numMatch) {
        newPrefix = numMatch[1] + (parseInt(numMatch[2]) + 1) + '. '
      }

      body.value = body.value.slice(0, pos) + '\n' + newPrefix + body.value.slice(pos)
      pushHistory()
      nextTick(() => { el.selectionStart = el.selectionEnd = pos + 1 + newPrefix.length })
      return
    }
  }

  // Tab → insert spaces (or 2-space indent)
  if (e.key === 'Tab') {
    e.preventDefault()
    if (e.shiftKey) {
      // Dedent: remove up to 2 leading spaces from current line
      const el = textarea.value!
      const pos = el.selectionStart
      const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
      const lineContent = body.value.slice(lineStart)
      if (lineContent.startsWith('  ')) {
        body.value = body.value.slice(0, lineStart) + lineContent.slice(2)
        nextTick(() => { el.selectionStart = el.selectionEnd = Math.max(lineStart, pos - 2) })
      }
    } else {
      insertAtCursor('  ')
    }
    return
  }
}

// ── Fullscreen escape ──
function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return

  // Close active overlays in priority order
  if (showTemplates.value) { showTemplates.value = false; return }
  if (showGeotag.value) { showGeotag.value = false; return }
  if (viewerOpen.value) { viewerOpen.value = false; return }
  if (showTagDropdown.value) { showTagDropdown.value = false; return }
  if (showFind.value) { showFind.value = false; return }
  if (showAi.value) { showAi.value = false; return }
  if (showRevisions.value) { showRevisions.value = false; return }
  if (showAnalysis.value) { showAnalysis.value = false; return }
  if (showRecording.value) { showRecording.value = false; return }
  if (showAttachments.value) { showAttachments.value = false; return }
  if (fullscreen.value) { fullscreen.value = false; return }

  // Close editor panel entirely
  close()
}

onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))

defineExpose({ isDirty, save })

// ── Save ──
async function save() {
  try {
    if (isNew.value) {
      if (!body.value.trim() && !title.value.trim()) { return }
      if (!title.value.trim()) {
        const t = prompt('Title for this entry:')
        if (t === null) return
        title.value = t
      }
      const entry = await entries.createEntry({
        entry_date: entryDate.value,
        title: title.value || null,
        body: body.value,
        tag_ids: tagIds.value.length ? tagIds.value : undefined,
      })
      // Apply pending geotag from modal (new entries)
      if (pendingGeotag.value && entry.id) {
        await setGeotag(entry.id, pendingGeotag.value)
        pendingGeotag.value = null
      }
      snapshot()
      entries.refreshAll()
      entries.currentEntry = entry
      ui.detailPanelOpen = true
      ui.startEditing(null)
    } else {
      if (!body.value.trim()) { alert('Body cannot be empty'); return }
      await entries.updateEntry(ui.editingEntryId!, { title: title.value || null, body: body.value, tag_ids: tagIds.value })
      snapshot()
      entries.refreshAll()
      ui.startEditing(null)
    }
  } catch (e: unknown) {
    console.error('[EntryEditor] save failed:', e)
    alert(`Save failed: ${errMsg(e)}`)
  }
}

function close() {
  entries.fetchCalendarMonth(new Date().getFullYear(), new Date().getMonth())
  ui.startEditing(null)
}

function onTranscribed(text: string) {
  body.value += `\n\n[Transcription]\n${text}`
  onInput()
}

async function openRecording() {
  if (showRecording.value) { showRecording.value = false; return }
  if (!hasEntry.value) {
    await save()
    if (!hasEntry.value) return // save failed or cancelled
  }
  showRecording.value = true
}

// ── Attachments ──
async function loadAttachments() {
  if (!hasEntry.value) { attachments.value = []; return }
  try {
    attachments.value = await mediaApi.listByEntry(ui.editingEntryId!)
  } catch { /* ignore */ }
}

async function openAttachDialog() {
  if (showAttachments.value) { showAttachments.value = false; return }
  if (!hasEntry.value) {
    await save()
    if (!hasEntry.value) return
  }
  await loadAttachments()
  showAttachments.value = true
  fileInput.value?.click()
}

async function handleFileUpload(files: FileList | null) {
  if (!files?.length || !hasEntry.value) return
  for (const file of Array.from(files)) {
    try {
      const m = await mediaApi.upload(ui.editingEntryId!, file)
      attachments.value.push(m)
    } catch (e: unknown) {
      alert(`Upload failed: ${errMsg(e)}`)
    }
  }
  entries.refreshAll()
}

async function removeAttachment(id: number) {
  try {
    await mediaApi.delete(id)
    attachments.value = attachments.value.filter(m => m.id !== id)
    entries.refreshAll()
  } catch (e: unknown) {
    alert(`Delete failed: ${errMsg(e)}`)
  }
}

function mediaIcon(type: string) {
  if (type === 'image' || type.startsWith('image/')) return Image
  if (type === 'video' || type.startsWith('video/')) return Film
  if (type === 'audio' || type.startsWith('audio/')) return Music
  return FileText
}

async function toggleTTS() {
  if (ttsPlaying.value) {
    if (ttsAudio) { ttsAudio.pause(); ttsAudio = null }
    ttsPlaying.value = false
    return
  }
  const text = [title.value, body.value].filter(Boolean).join('\n\n')
  if (!text.trim()) return
  ttsLoading.value = true
  try {
    // Use streaming URL for saved entries — starts playback immediately
    if (hasEntry.value) {
      const url = ttsApi.entryUrl(ui.editingEntryId!)
      ttsAudio = new Audio(url)
    } else {
      // For new entries, generate audio blob then play
      const blob = await ttsApi.speakBlob(text)
      const blobUrl = URL.createObjectURL(blob)
      ttsAudio = new Audio(blobUrl)
      ttsAudio.addEventListener('ended', () => URL.revokeObjectURL(blobUrl))
      ttsAudio.addEventListener('error', () => URL.revokeObjectURL(blobUrl))
    }
    ttsAudio.addEventListener('ended', () => { ttsPlaying.value = false })
    ttsAudio.addEventListener('error', () => { ttsPlaying.value = false })
    ttsPlaying.value = true
    ttsLoading.value = false
    ttsAudio.play()
  } catch (e: unknown) {
    alert(`Read Aloud failed: ${errMsg(e)}`)
  } finally {
    ttsLoading.value = false
  }
}

async function handleDelete() {
  if (isNew.value) return
  if (!confirm('Delete this entry?')) return
  try {
    await entries.deleteEntry(ui.editingEntryId!)
  } catch {
    // Entry already gone — just close
  }
  entries.fetchCalendarMonth(new Date().getFullYear(), new Date().getMonth())
  ui.startEditing(null)
}

function onTemplateSelect(t: { name: string; body: string }) {
  if (!title.value.trim()) {
    title.value = t.name
  }
  if (isNew.value || !body.value.trim()) {
    body.value = t.body
  } else {
    body.value += '\n\n' + t.body
  }
  onInput()
}

// ── AI Tag Suggestions ──
async function fetchSuggestedTags() {
  if (!body.value.trim()) return
  suggestingTags.value = true
  suggestedTags.value = []
  try {
    const res = await suggestTags(body.value)
    suggestedTags.value = res.tags
  } catch { /* ignore */ }
  finally { suggestingTags.value = false }
}

async function applySuggestedTag(name: string) {
  const tagsStore = useTagsStore()
  await tagsStore.fetchTree()
  const existing = tagsStore.tags.find(t => t.name.toLowerCase() === name.toLowerCase())
  if (existing) {
    if (!tagIds.value.includes(existing.id)) tagIds.value.push(existing.id)
  } else {
    const created = await tagsStore.createTag({ name })
    tagIds.value.push(created.id)
  }
  suggestedTags.value = suggestedTags.value.filter(t => t !== name)
  onInput()
}

// ── Entry Analysis ──
async function toggleAnalysis() {
  if (showAnalysis.value) { showAnalysis.value = false; return }
  if (!hasEntry.value) return
  showAnalysis.value = true
  analysisLoading.value = true
  analysis.value = null
  similarEntries.value = []
  try {
    analysis.value = await getEntryAnalysis(ui.editingEntryId!)
  } catch { /* ignore */ }
  finally { analysisLoading.value = false }
}

async function fetchSimilar() {
  if (!hasEntry.value) return
  similarLoading.value = true
  try {
    const res = await findSimilar(ui.editingEntryId!)
    similarEntries.value = res.similar
  } catch { /* ignore */ }
  finally { similarLoading.value = false }
}

function gotoEntry(entryId: number) {
  entries.currentEntry = null
  ui.detailPanelOpen = true
  entries.fetchEntry(entryId).then(e => { if (e) entries.currentEntry = e })
}

// Active formatting detection
const activeFormats = computed(() => {
  const el = textarea.value
  if (!el) return new Set<string>()
  const pos = el.selectionStart
  const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
  const currentLine = body.value.slice(lineStart, pos)
  const s = new Set<string>()
  if (currentLine.startsWith('# ')) s.add('h1')
  if (currentLine.startsWith('## ')) s.add('h2')
  if (currentLine.startsWith('- ') || currentLine.startsWith('* ') || currentLine.startsWith('+ ')) s.add('ul')
  if (/^\d+\.\s/.test(currentLine)) s.add('ol')
  if (currentLine.startsWith('> ')) s.add('quote')

  // Inline: check surrounding text
  const before = body.value.slice(Math.max(0, pos - 10), pos)
  const after = body.value.slice(pos, pos + 10)
  if ((before.endsWith('**') && after.startsWith('**')) || (before.endsWith('**') && body.value.slice(pos).startsWith('**'))) s.add('bold')
  if ((before.endsWith('*') && !before.endsWith('**') && after.startsWith('*')) || (before.endsWith('*') && !before.endsWith('**') && body.value.slice(pos).startsWith('*'))) s.add('italic')
  return s
})
</script>

<template>
  <div
    class="flex flex-col h-full"
    :class="fullscreen ? 'fixed inset-0 z-[100] bg-editor' : ''"
  >
    <!-- Header: Title + Date + New + controls -->
    <div class="flex items-center gap-2 px-3 py-1.5 border-b border-border">
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


    <!-- Formatting toolbar (two rows) -->
    <div class="border-b border-border bg-editor/50" v-if="!showPreview">
      <!-- Row 1: Font + inline formatting + undo/redo -->
      <div class="flex items-center gap-0.5 px-1.5 py-0.5">
        <select
          class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
          :value="ui.fontFamily"
          @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)"
        >
          <option value="system-ui">System</option>
          <option value="'Segoe UI', sans-serif">Segoe UI</option>
          <option value="'Inter', sans-serif">Inter</option>
          <option value="'Roboto', sans-serif">Roboto</option>
          <option value="'Lora', serif">Lora</option>
          <option value="'Merriweather', serif">Merriweather</option>
          <option value="'JetBrains Mono', monospace">JetBrains Mono</option>
          <option value="monospace">Monospace</option>
        </select>
        <select
          class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
          :value="ui.fontSize"
          @change="ui.setFontSize(Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="s in [12, 13, 14, 15, 16, 18, 20, 22, 24]" :key="s" :value="s">{{ s }}px</option>
        </select>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
          :disabled="undoStack.length < 2"
          title="Undo (Ctrl+Z)"
          @click="fmt.undo"
        ><Undo2 :size="13" /></button>
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
          :disabled="!redoStack.length"
          title="Redo (Ctrl+Y)"
          @click="fmt.redo"
        ><Redo2 :size="13" /></button>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('bold') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Bold (Ctrl+B)" @click="fmt.bold"><Bold :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('italic') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Italic (Ctrl+I)" @click="fmt.italic"><Italic :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Strikethrough (Ctrl+U)" @click="fmt.strikethrough"><Strikethrough :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Inline code (Ctrl+K)" @click="fmt.code"><Code :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Code block" @click="fmt.codeBlock"><Type :size="13" /></button>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Link" @click="fmt.link"><Link :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Image" @click="fmt.image"><Image :size="13" /></button>
        <span class="flex-1" />
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          :class="showFind ? 'bg-accent/20 text-accent' : ''"
          title="Find & Replace (Ctrl+F)"
          @click="showFind = !showFind"
        ><Search :size="13" /></button>
      </div>
      <!-- Row 2: Block formatting -->
      <div class="flex items-center gap-0.5 px-1.5 py-0.5">
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('h1') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Heading 1" @click="fmt.h1"><Heading1 :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('h2') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Heading 2" @click="fmt.h2"><Heading2 :size="13" /></button>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('ul') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Bullet list" @click="fmt.ul"><List :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('ol') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Numbered list" @click="fmt.ol"><ListOrdered :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('quote') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Blockquote" @click="fmt.quote"><Quote :size="13" /></button>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Checkbox" @click="fmt.checkbox"><CheckSquare :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Table" @click="fmt.table"><Table :size="13" /></button>
        <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Horizontal rule" @click="fmt.hr"><Minus :size="13" /></button>
      </div>
    </div>

    <!-- Find & Replace bar -->
    <div v-if="showFind" class="flex items-center gap-1.5 px-2 py-1 border-b border-border bg-surface">
      <Search :size="12" class="text-text-muted shrink-0" />
      <input
        v-model="findQuery"
        class="flex-1 bg-transparent border-b border-border focus:border-accent px-1 py-0.5 text-xs text-text-primary outline-none"
        placeholder="Find..."
        @keydown="onKeydown"
      />
      <span class="text-[10px] text-text-muted whitespace-nowrap">
        {{ findIndex >= 0 ? (findIndex + 1) : 0 }}/{{ findCount }}
      </span>
      <button class="p-0.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" title="Previous" @click="jumpToMatch(-1)">
        <ChevronUp :size="12" />
      </button>
      <button class="p-0.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" title="Next" @click="jumpToMatch(1)">
        <ChevronDown :size="12" />
      </button>
      <span class="w-px h-3 bg-border" />
      <input
        v-model="replaceQuery"
        class="flex-1 bg-transparent border-b border-border focus:border-accent px-1 py-0.5 text-xs text-text-primary outline-none"
        placeholder="Replace..."
      />
      <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer" @click="replaceOne">Replace</button>
      <button class="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer" @click="replaceAll">All</button>
      <button class="p-0.5 rounded hover:bg-surface-hover text-text-muted cursor-pointer" @click="showFind = false">
        <X :size="12" />
      </button>
    </div>

    <!-- Body + Panels -->
    <div class="flex-1 flex flex-col min-h-0">
      <!-- Textarea / Preview -->
      <div class="flex-1 overflow-y-auto relative min-h-0">
        <!-- Encrypted lock screen -->
        <div v-if="isEncrypted" class="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
          <Lock :size="32" class="text-accent opacity-60" />
          <div class="text-sm font-medium text-text-secondary">This entry is encrypted</div>
          <div class="text-xs">Click the unlock button to decrypt</div>
        </div>
        <template v-else>
          <textarea
            v-if="!showPreview"
            ref="textarea"
            v-model="body"
            class="w-full h-full resize-none bg-transparent p-4 text-text-primary outline-none leading-relaxed placeholder:text-text-muted/60"
            :style="{ fontFamily: 'var(--editor-font)', fontSize: 'var(--editor-font-size)' }"
            placeholder="Write your thoughts..."
            @input="onInput"
            @keydown="onTextareaKeydown"
            @keydown.capture="onKeydown"
          />
          <div
            v-else
            class="p-4 md-body max-w-none text-text-primary"
            :style="{ fontFamily: 'var(--editor-font)', fontSize: 'var(--editor-font-size)' }"
            v-html="renderedPreview"
          />
        </template>
      </div>

      <!-- AI Panel -->
      <div v-if="showAi && body" class="border-t border-border p-3 max-h-[40vh] overflow-y-auto">
        <AiPanel :text="body" @apply="(t) => { body = t; onInput() }" />
      </div>

      <!-- Revision Panel -->
      <div v-if="showRevisions && hasEntry" class="border-t border-border p-3 max-h-[40vh] overflow-y-auto">
        <RevisionPanel :entryId="ui.editingEntryId!" @restored="() => { showRevisions = false }" />
      </div>

      <!-- Analysis Panel -->
      <div v-if="showAnalysis && hasEntry" class="border-t border-border p-3 max-h-[40vh] overflow-y-auto space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-text-primary flex items-center gap-1"><BarChart3 :size="14" /> AI Analysis</span>
          <button @click="showAnalysis = false" class="text-text-muted hover:text-text-primary"><X :size="12" /></button>
        </div>
        <div v-if="analysisLoading" class="text-xs text-text-secondary flex items-center gap-1"><Loader :size="12" class="animate-spin" /> Analyzing...</div>
        <template v-else-if="analysis">
          <!-- Sentiment -->
          <div v-if="analysis.sentiment" class="space-y-1">
            <div class="text-[10px] font-medium text-text-muted uppercase tracking-wide">Sentiment</div>
            <div class="flex items-center gap-2">
              <span class="text-xs text-text-primary capitalize">{{ analysis.sentiment.primary_emotion }}</span>
              <span v-if="analysis.sentiment.secondary_emotion" class="text-[10px] text-text-muted">+ {{ analysis.sentiment.secondary_emotion }}</span>
              <div class="flex-1 h-1.5 bg-surface-hover rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all"
                  :class="analysis.sentiment.valence >= 0 ? 'bg-green-400' : 'bg-red-400'"
                  :style="{ width: Math.abs(analysis.sentiment.valence) * 100 + '%' }" />
              </div>
              <span class="text-[10px] text-text-muted">Intensity {{ analysis.sentiment.intensity }}/10</span>
            </div>
          </div>
          <!-- Summary -->
          <div v-if="analysis.summary">
            <div class="text-[10px] font-medium text-text-muted uppercase tracking-wide mb-0.5">Summary</div>
            <div class="text-xs text-text-primary bg-surface-hover rounded p-2">{{ analysis.summary }}</div>
          </div>
          <!-- Reflection Prompts -->
          <div v-if="analysis.reflection_prompts.length">
            <div class="text-[10px] font-medium text-text-muted uppercase tracking-wide mb-0.5">Reflection Prompts</div>
            <ul class="space-y-1">
              <li v-for="(p, i) in analysis.reflection_prompts" :key="i" class="text-xs text-text-secondary flex items-start gap-1">
                <Lightbulb :size="10" class="text-accent shrink-0 mt-0.5" /> {{ p }}
              </li>
            </ul>
          </div>
          <!-- Similar Entries -->
          <div class="pt-2 border-t border-border">
            <button @click="fetchSimilar" :disabled="similarLoading"
              class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 cursor-pointer mb-2">
              <Loader v-if="similarLoading" :size="10" class="animate-spin" />
              <SearchIcon v-else :size="10" />
              {{ similarLoading ? 'Searching...' : 'Find similar entries' }}
            </button>
            <div v-if="similarEntries.length" class="space-y-1">
              <div v-for="s in similarEntries" :key="s.id"
                class="flex items-center justify-between p-1.5 bg-surface-hover rounded cursor-pointer hover:bg-surface-hover/80"
                @click="gotoEntry(s.id)">
                <div>
                  <div class="text-xs text-text-primary">{{ s.title || 'Untitled' }}</div>
                  <div class="text-[10px] text-text-muted">{{ s.entry_date }}</div>
                </div>
                <span class="text-[10px] text-accent">{{ (s.similarity_score * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="text-xs text-text-muted">No analysis available. Make sure Ollama is running.</div>
      </div>

      <!-- Recording Panel -->
      <div v-if="showRecording && hasEntry" class="border-t border-border p-3">
        <RecordingPanel :entryId="ui.editingEntryId!" @transcribed="onTranscribed" />
      </div>

      <!-- Attachments Panel -->
      <div v-if="showAttachments && hasEntry" class="border-t border-border p-3 max-h-[40vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-medium text-text-secondary">Attachments ({{ attachments.length }})</span>
          <button class="text-xs text-accent hover:text-accent-hover cursor-pointer" @click="fileInput?.click()">+ Add more</button>
        </div>
        <div v-if="!attachments.length" class="text-xs text-text-muted text-center py-3">
          No attachments yet. Click the paperclip button to add files.
        </div>
        <div v-else class="space-y-1.5">
          <div
            v-for="(m, idx) in attachments"
            :key="m.id"
            class="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-hover cursor-pointer hover:bg-surface-hover/80"
            @click="viewerIndex = idx; viewerOpen = true"
          >
            <!-- Thumbnail for images -->
            <img v-if="m.media_type === 'image' || m.media_type.startsWith('image/')" :src="mediaApi.fileUrl(m.id)" class="w-8 h-8 rounded object-cover shrink-0" />
            <component v-else :is="mediaIcon(m.media_type)" :size="16" class="text-accent shrink-0" />
            <span class="text-xs text-text-primary truncate flex-1">{{ m.filename }}</span>
            <span class="text-[10px] text-text-muted shrink-0">{{ formatFileSize(m.file_size) }}</span>
            <button class="p-0.5 text-text-muted hover:text-red-400 cursor-pointer" @click.stop="removeAttachment(m.id)" title="Remove">
              <Trash2 :size="12" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Status bar + Bottom controls -->
    <div class="border-t border-border">
      <!-- Stats bar -->
      <div class="flex items-center gap-3 px-3 py-0.5 text-[10px] text-text-muted bg-editor/30">
        <span class="flex items-center gap-0.5"><AlignLeft :size="10" /> {{ stats.words }} words</span>
        <span>{{ stats.chars }} chars</span>
        <span>{{ stats.lines }} lines</span>
        <span>{{ stats.paragraphs }} paragraphs</span>
        <span class="flex items-center gap-0.5"><Clock :size="10" /> {{ stats.readMins }} min read</span>
        <span class="flex-1" />
        <span v-if="saveTimer">Saving...</span>
        <span v-else-if="body.trim()">Saved</span>
      </div>

      <!-- Controls bar: Edit/Preview + Tags + Save -->
      <div class="flex items-center gap-1.5 px-3 py-1.5 relative">
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors"
          :class="!showPreview ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          @click="showPreview = false"
        >
          <Edit3 :size="13" />
        </button>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors"
          :class="showPreview ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          @click="showPreview = true"
        >
          <Eye :size="13" />
        </button>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded text-[11px] cursor-pointer transition-colors relative"
          :class="tagIds.length ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          @click="showTagDropdown = !showTagDropdown"
          title="Tags"
        >
          <Tag :size="13" />
          <span v-if="tagIds.length" class="text-[9px]">{{ tagIds.length }}</span>
        </button>

        <!-- Tag dropdown -->
        <div
          v-if="showTagDropdown && !isEncrypted"
          class="absolute bottom-full left-0 right-0 mb-1 mx-3 bg-surface border border-border rounded-lg shadow-xl p-2 z-50"
        >
          <TagList v-model="tagIds" />
          <!-- AI Tag Suggestions -->
          <div v-if="aiAvailable" class="mt-2 pt-2 border-t border-border space-y-1.5">
            <button @click="fetchSuggestedTags" :disabled="suggestingTags || !body.trim()"
              class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 cursor-pointer">
              <Loader v-if="suggestingTags" :size="10" class="animate-spin" />
              <Sparkles v-else :size="10" />
              {{ suggestingTags ? 'Suggesting...' : 'Suggest tags' }}
            </button>
            <div v-if="suggestedTags.length" class="flex flex-wrap gap-1">
              <button v-for="tag in suggestedTags" :key="tag" @click="applySuggestedTag(tag)"
                class="px-2 py-0.5 rounded-full text-[10px] bg-accent/15 text-accent hover:bg-accent/30 cursor-pointer transition-colors">
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
          :class="showAi ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="showAi = !showAi"
          title="AI Tools"
        ><Sparkles :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="showRevisions ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="showRevisions = !showRevisions"
          title="Version History"
        ><History :size="13" /></button>
        <button
          v-if="aiAvailable && hasEntry"
          class="p-1 rounded cursor-pointer transition-colors"
          :class="showAnalysis ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="toggleAnalysis"
          title="AI Analysis"
        ><BarChart3 :size="13" /></button>
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          @click="showGeotag = true"
          title="Set Location"
        ><MapPin :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="showRecording ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="openRecording"
          title="Voice Recording"
        ><Mic :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="attachments.length ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="openAttachDialog"
          title="Attach files"
        >
          <div class="flex items-center gap-0.5">
            <Paperclip :size="13" />
            <span v-if="attachments.length" class="text-[9px] leading-none">{{ attachments.length }}</span>
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
          :class="ttsPlaying ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
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

    <!-- Geotag Modal -->
    <GeotagModal
      v-if="showGeotag && (ui.editingEntryId || isNew)"
      :entryId="ui.editingEntryId ?? -1"
      @close="showGeotag = false"
      @saved="showGeotag = false"
      @pending="(data) => { pendingGeotag = data; showGeotag = false }"
    />

    <MediaViewer
      v-if="viewerOpen"
      :items="attachments"
      v-model:index="viewerIndex"
      @close="viewerOpen = false"
    />

    <TemplatePicker
      v-if="showTemplates"
      @select="onTemplateSelect"
      @close="showTemplates = false"
    />
  </div>
</template>
