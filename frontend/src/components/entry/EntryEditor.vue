<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useEntriesStore } from '../../stores/entries'
import { useTagsStore } from '../../stores/tags'
import { useUiStore } from '../../stores/ui'
import {
  X, Eye, Edit3, Bold, Italic, Strikethrough, Heading1, Heading2,
  List, ListOrdered, Quote, Code, Link, Image, Minus,
  Undo2, Redo2, Maximize2, Minimize2, Search, Type, AlignLeft, AlignCenter, AlignRight, AlignJustify, Highlighter, Smile,
  Table, CheckSquare, Clock, ChevronUp, ChevronDown,
  Sparkles, History, MapPin, Plus, Lock, Trash2, Tag, Mic, Volume2, Paperclip, LayoutTemplate,
  Loader, Pause, Focus, Layout, Copy, Scissors
} from 'lucide-vue-next'
import EncryptionBadge from './EncryptionBadge.vue'
import GeotagModal from './GeotagModal.vue'
import TagList from '../tags/TagList.vue'
import MediaViewer from '../media/MediaViewer.vue'
import TemplatePicker from '../templates/TemplatePicker.vue'
import EmojiPicker from '../common/EmojiPicker.vue'
import { setGeotag } from '../../api/geotagging'
import { aiStatus, suggestTags, runOCR } from '../../api/ai'
import { encryptText, decryptText } from '../../api/encryption'
import { ttsApi } from '../../api/tts'
import { mediaApi } from '../../api/media'
import { useLocalStorage } from '@vueuse/core'
import { marked } from 'marked'

marked.use({ gfm: true, breaks: true })
import DOMPurify from 'dompurify'
import type { MediaResponse } from '../../types'

const entries = useEntriesStore()
const ui = useUiStore()

const isNew = computed(() => ui.editingEntryId === -1)
const hasEntry = computed(() => ui.editingEntryId != null && ui.editingEntryId > 0)
const title = ref('')
const body = ref('')
const tagIds = ref<number[]>([])
const entryDate = ref('')
const entryLat = ref<number | null>(null)
const entryLon = ref<number | null>(null)
const entryLocationName = ref<string | null>(null)
const showPreview = ref(false)
const fullscreen = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)
const showGeotag = ref(false)
const showTemplates = ref(false)
const showEmoji = ref(false)
const aiProcessing = ref(false)
const attachments = ref<MediaResponse[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const viewerOpen = ref(false)
const viewerIndex = ref(0)
const showTagDropdown = ref(false)
const aiAvailable = ref<boolean | null>(null)
const suggestedTags = ref<string[]>([])
const suggestingTags = ref(false)
const ttsPlaying = ref(false)
const ttsLoading = ref(false)
let ttsAudio: HTMLAudioElement | null = null
const isEncrypted = ref(false)
const focusMode = ref(false)
const typewriterMode = ref(false)
const showContextMenu = ref(false)
const contextMenuPos = ref({ x: 0, y: 0 })
const pendingGeotag = ref<{ latitude: number; longitude: number; location_name: string | null } | null>(null)
const defaultTemplateId = useLocalStorage<number | null>('diarium-default-template', null)
const autoGeotag = useLocalStorage<boolean>('diarium-auto-geotag', false)

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
  alignLeft: () => wrap('<div style="text-align: left">\n', '\n</div>', 'left aligned text'),
  alignCenter: () => wrap('<div style="text-align: center">\n', '\n</div>', 'centered text'),
  alignRight: () => wrap('<div style="text-align: right">\n', '\n</div>', 'right aligned text'),
  alignJustify: () => wrap('<div style="text-align: justify">\n', '\n</div>', 'justified text'),
  highlight: () => wrap('<mark>', '</mark>', 'highlighted text'),
}

const renderedPreview = computed(() => {
  let html = marked(body.value) as string
  html = html.replace(/&lt;!--ENC\{([^}]+)\}--&gt;/g, (_, enc) => {
    return `<span class="enc-block cursor-pointer bg-accent/10 text-accent px-1.5 py-0.5 rounded border border-accent/20 text-[11px] font-medium" data-enc="${enc}">🔒 Decrypt selection</span>`
  })
  // Also handle raw HTML if marked didn't escape it (unlikely with default settings but just in case)
  html = html.replace(/<!--ENC\{([^}]+)\}-->/g, (_, enc) => {
    return `<span class="enc-block cursor-pointer bg-accent/10 text-accent px-1.5 py-0.5 rounded border border-accent/20 text-[11px] font-medium" data-enc="${enc}">🔒 Decrypt selection</span>`
  })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-enc'] })
})

// ── Load entry data ──
async function loadEntry() {
  body.value = ''
  title.value = ''
  tagIds.value = []
  entryLat.value = null
  entryLon.value = null
  entryLocationName.value = null

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
          if (!title.value) title.value = tmpl.name
        }
      } catch { /* ignore */ }
    }
    // Apply default title if no template set one
    if (!title.value && ui.defaultTitle) {
      title.value = ui.defaultTitle
    }

    // Auto-geotag new entries if enabled
    if (autoGeotag.value && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const lat = pos.coords.latitude
          const lon = pos.coords.longitude
          if (isNew.value && !pendingGeotag.value) {
            try {
              const { reverseGeocode } = await import('../../utils/geocoding')
              const placeName = await reverseGeocode(lat, lon)
              pendingGeotag.value = {
                latitude: Math.round(lat * 1000000) / 1000000,
                longitude: Math.round(lon * 1000000) / 1000000,
                location_name: placeName || null,
              }
            } catch {
              pendingGeotag.value = {
                latitude: Math.round(lat * 1000000) / 1000000,
                longitude: Math.round(lon * 1000000) / 1000000,
                location_name: null,
              }
            }
          }
        },
        () => { /* location denied or unavailable — silently skip */ },
        { enableHighAccuracy: false, timeout: 5000 }
      )
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
      entryLat.value = entry.latitude ?? null
      entryLon.value = entry.longitude ?? null
      entryLocationName.value = entry.location_name ?? null
    }
  }
  pushHistory()
  snapshot()
  loadAttachments()
}

onMounted(() => {
  loadEntry()
  window.addEventListener('click', async (e) => {
    showContextMenu.value = false
    const target = e.target as HTMLElement
    if (target.classList.contains('enc-block')) {
      const enc = target.getAttribute('data-enc')
      if (!enc) return
      const passphrase = prompt('Enter passphrase to decrypt:')
      if (!passphrase) return
      try {
        const res = await decryptText(enc, passphrase)
        target.textContent = res.decrypted
        target.classList.remove('bg-accent/10', 'text-accent')
        target.classList.add('bg-surface-hover', 'text-text-primary')
      } catch (e: unknown) {
        alert('Decryption failed: wrong passphrase?')
      }
    }
  })
})
onUnmounted(() => {
  window.removeEventListener('click', () => { showContextMenu.value = false })
})
watch([() => ui.editingEntryId, () => ui.newEntryDate], () => { loadEntry(); loadAttachments() })

// Check AI availability once
aiStatus().then(s => { aiAvailable.value = s.ollama_available && s.model_loaded }).catch(() => { aiAvailable.value = false })

async function onEncryptionChange(encrypted: boolean) {
  isEncrypted.value = encrypted
  await loadEntry()
}

async function onGeotagSaved() {
  showGeotag.value = false
  if (hasEntry.value) {
    try {
      const entry = await entries.fetchEntry(ui.editingEntryId!)
      if (entry) {
        entryLat.value = entry.latitude ?? null
        entryLon.value = entry.longitude ?? null
        entryLocationName.value = entry.location_name ?? null
      }
    } catch {
      // Entry may have been deleted or DB reset — clear stale refs
      entryLat.value = null
      entryLon.value = null
      entryLocationName.value = null
    }
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
const autosaveMs = computed(() => {
  const secs = parseInt(localStorage.getItem('diarium-autosave-interval') || '2')
  return (isNaN(secs) ? 2 : secs) * 1000
})

function onInput() {
  pushHistory()
  markDirty()

  if (typewriterMode.value) {
    nextTick(() => {
      const el = textarea.value
      if (!el) return
      const { selectionStart } = el
      const lines = body.value.slice(0, selectionStart).split('\n').length
      const lineHeight = 24 // approximate px
      const targetScroll = (lines * lineHeight) - (el.clientHeight / 2)
      el.scrollTo({ top: targetScroll, behavior: 'smooth' })
    })
  }

  if (saveTimer) clearTimeout(saveTimer)
  if (!body.value.trim()) return

  saveTimer = setTimeout(async () => {
    if (isNew.value) {
      try {
        const entry = await entries.createEntry({
          entry_date: entryDate.value,
          title: title.value || null,
          body: body.value,
          tag_ids: tagIds.value
        })
        ui.editingEntryId = entry.id
        snapshot()
      } catch (e: unknown) { /* ignore auto-save failures */ }
    } else {
      entries.updateEntry(ui.editingEntryId!, { title: title.value || null, body: body.value, tag_ids: tagIds.value })
    }
  }, autosaveMs.value)
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
function onContextMenu(e: MouseEvent) {
  e.preventDefault()
  contextMenuPos.value = { x: e.clientX, y: e.y }
  showContextMenu.value = true
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return

  // Close active overlays in priority order
  if (showTemplates.value) { showTemplates.value = false; return }
  if (showContextMenu.value) { showContextMenu.value = false; return }
  if (ui.activeDrawer) { ui.closeDrawer(); return }
  if (showEmoji.value) { showEmoji.value = false; return }
  if (showGeotag.value) { showGeotag.value = false; return }
  if (viewerOpen.value) { viewerOpen.value = false; return }
  if (showTagDropdown.value) { showTagDropdown.value = false; return }
  if (showFind.value) { showFind.value = false; return }
  if (fullscreen.value) { fullscreen.value = false; return }

  // Close editor panel entirely
  close()
}

onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))

defineExpose({
  isDirty, save, body, onInput, hasEntry, entryId: computed(() => ui.editingEntryId),
  attachments, handleFileUpload, removeAttachment, runOcrTool, loadAttachments,
  triggerFileInput: () => fileInput.value?.click(),
  openViewer: (index: number) => { viewerIndex.value = index; viewerOpen.value = true },
})

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
  entries.refreshAll()
  ui.startEditing(null)
}

function onEmojiSelect(emoji: string) {
  insertAtCursor(emoji)
  showEmoji.value = false
}

function copyToClipboard() {
  const text = getSelection()
  if (text) navigator.clipboard.writeText(text)
}

function cutToClipboard() {
  const text = getSelection()
  if (text) {
    navigator.clipboard.writeText(text)
    applyToSelection('')
  }
}

function getSelection() {
  const el = textarea.value
  if (!el) return ''
  return body.value.slice(el.selectionStart, el.selectionEnd).trim()
}

function applyToSelection(newText: string) {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart
  const end = el.selectionEnd
  body.value = body.value.slice(0, start) + newText + body.value.slice(end)
  pushHistory()
  markDirty()
  nextTick(() => {
    el.focus()
    el.selectionStart = start
    el.selectionEnd = start + newText.length
  })
}

async function openRecording() {
  if (ui.activeDrawer === 'recording') { ui.closeDrawer(); return }
  if (!hasEntry.value) {
    await save()
    if (!hasEntry.value) return
  }
  ui.activeDrawer = 'recording'
}

// ── Attachments ──
async function loadAttachments() {
  if (!hasEntry.value) { attachments.value = []; return }
  try {
    attachments.value = await mediaApi.listByEntry(ui.editingEntryId!)
  } catch { /* ignore */ }
}

async function openAttachDialog() {
  if (ui.activeDrawer === 'attachments') { ui.closeDrawer(); return }
  if (!hasEntry.value) {
    await save()
    if (!hasEntry.value) return
  }
  await loadAttachments()
  ui.activeDrawer = 'attachments'
  nextTick(() => fileInput.value?.click())
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

async function runOcrTool(mediaId: number) {
  aiProcessing.value = true
  try {
    const res = await runOCR(mediaId)
    if (res.extracted_text) {
      body.value += `\n\n[OCR Text]\n${res.extracted_text}`
      pushHistory()
      markDirty()
      alert('Text extracted and appended to entry.')
    } else {
      alert('No text detected in image.')
    }
  } catch (e: unknown) {
    alert(`OCR failed: ${errMsg(e)}`)
  } finally {
    aiProcessing.value = false
  }
}

async function encryptSelection() {
  const text = getSelection()
  if (!text) {
    alert('Please select some text to encrypt.')
    return
  }
  const passphrase = prompt('Enter a passphrase to encrypt this selection:')
  if (!passphrase) return

  try {
    const res = await encryptText(text, passphrase)
    applyToSelection(`<!--ENC{${res.encrypted}}-->`)
    alert('Selection encrypted.')
  } catch (e: unknown) {
    alert(`Encryption failed: ${errMsg(e)}`)
  }
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
  entries.refreshAll()
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
  const before = body.value.slice(Math.max(0, pos - 20), pos)
  const after = body.value.slice(pos, pos + 20)
  const full = body.value.slice(Math.max(0, pos - 40), pos + 40)

  if ((before.endsWith('**') && after.startsWith('**')) || (before.endsWith('**') && body.value.slice(pos).startsWith('**'))) s.add('bold')
  if ((before.endsWith('*') && !before.endsWith('**') && after.startsWith('*')) || (before.endsWith('*') && !before.endsWith('**') && body.value.slice(pos).startsWith('*'))) s.add('italic')
  if (full.includes('<mark>') && full.includes('</mark>')) s.add('highlight')
  if (full.includes('text-align: left')) s.add('alignLeft')
  if (full.includes('text-align: center')) s.add('alignCenter')
  if (full.includes('text-align: right')) s.add('alignRight')
  if (full.includes('text-align: justify')) s.add('alignJustify')
  return s
})
</script>

<template>
  <div
    class="flex flex-col h-full"
    :class="[
      fullscreen ? 'fixed inset-0 z-[100] bg-editor' : '',
      focusMode ? 'bg-editor' : ''
    ]"
  >
    <!-- Header: Title + Date + New + controls -->
    <div class="flex items-center gap-2 px-3 py-1.5 border-b border-border" v-if="!focusMode">
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
    <div class="border-b border-border bg-editor/50" v-if="!showPreview && !focusMode">
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
        <span class="w-px h-4 bg-border mx-0.5" />
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="showEmoji ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          title="Insert Emoji"
          @click="showEmoji = !showEmoji"
        ><Smile :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="focusMode ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          title="Focus Mode"
          @click="focusMode = !focusMode"
        ><Focus :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="typewriterMode ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          title="Typewriter Mode"
          @click="typewriterMode = !typewriterMode"
        ><Layout :size="13" /></button>
        <span class="flex-1" />
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          :class="showFind ? 'bg-accent/20 text-accent' : ''"
          title="Find & Replace (Ctrl+F)"
          @click="showFind = !showFind"
        ><Search :size="13" /></button>
      </div>
      <!-- Row 2: Block formatting + Alignment + Highlighter -->
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
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('alignLeft') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Align left" @click="fmt.alignLeft"><AlignLeft :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('alignCenter') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Align center" @click="fmt.alignCenter"><AlignCenter :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('alignRight') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Align right" @click="fmt.alignRight"><AlignRight :size="13" /></button>
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('alignJustify') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Align justify" @click="fmt.alignJustify"><AlignJustify :size="13" /></button>
        <span class="w-px h-4 bg-border mx-0.5" />
        <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
          :class="activeFormats.has('highlight') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
          title="Highlight" @click="fmt.highlight"><Highlighter :size="13" /></button>
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
    <div class="flex-1 flex min-h-0 relative overflow-hidden">
      <!-- Main Editor Area -->
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
            @contextmenu="onContextMenu"
          />
          <div
            v-else
            class="p-4 md-body max-w-none text-text-primary"
            :style="{ fontFamily: 'var(--editor-font)', fontSize: 'var(--editor-font-size)' }"
            v-html="renderedPreview"
          />
        </template>
      </div>
    </div>
  </div>

  <!-- Status bar + Bottom controls -->
  <div class="border-t border-border" v-if="!focusMode">
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
          class="p-1 rounded cursor-pointer transition-colors"
          :class="ui.activeDrawer === 'ai' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          title="AI Smart Actions"
          @click="ui.toggleDrawer('ai')"
        >
          <Sparkles :size="13" />
        </button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="ui.activeDrawer === 'revisions' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="hasEntry && ui.toggleDrawer('revisions')"
          title="Version History"
        ><History :size="13" /></button>
        <div class="relative group">
          <button
            class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
            @click="showGeotag = true"
          ><MapPin :size="13" /></button>
          <div v-if="entryLocationName"
            class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 rounded text-[10px] text-white bg-gray-800 whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50"
          >{{ entryLocationName }}</div>
        </div>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="ui.activeDrawer === 'recording' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
          @click="openRecording"
          title="Voice Recording"
        ><Mic :size="13" /></button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="ui.activeDrawer === 'attachments' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
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
      :lat="entryLat"
      :lon="entryLon"
      :name="entryLocationName"
      @close="showGeotag = false"
      @saved="onGeotagSaved"
      @pending="(data) => { pendingGeotag = data; showGeotag = false }"
    />

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

    <!-- Context Menu -->
    <div
      v-if="showContextMenu"
      class="fixed z-[200] w-48 bg-surface border border-border rounded shadow-2xl py-1"
      :style="{ left: contextMenuPos.x + 'px', top: contextMenuPos.y + 'px' }"
      @click="showContextMenu = false"
    >
      <button @click="copyToClipboard" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
        <Copy :size="12" /> Copy
      </button>
      <button @click="cutToClipboard" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
        <Scissors :size="12" /> Cut
      </button>
      <div class="h-px bg-border my-1" />
      <button @click="fmt.bold" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
        <Bold :size="12" /> Bold
      </button>
      <button @click="fmt.italic" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
        <Italic :size="12" /> Italic
      </button>
      <button @click="encryptSelection" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2">
        <Lock :size="12" /> Encrypt Selection
      </button>
      <div class="h-px bg-border my-1" />
      <button @click="ui.toggleDrawer('ai')" class="w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover flex items-center gap-2 text-accent">
        <Sparkles :size="12" /> AI Smart Actions
      </button>
    </div>
  </div>
</template>

<style scoped>
.md-body :deep(.enc-block) {
  display: inline-block;
  transition: all 0.2s;
}
.md-body :deep(.enc-block:hover) {
  opacity: 0.8;
  transform: translateY(-1px);
}
</style>
