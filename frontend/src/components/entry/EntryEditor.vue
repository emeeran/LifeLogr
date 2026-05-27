<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch, defineAsyncComponent } from 'vue'
import { useEntriesStore } from '../../stores/entries'
import { useTagsStore } from '../../stores/tags'
import { useUiStore } from '../../stores/ui'
import {
  X, Eye, Edit3, Minimize2, Maximize2,
  Search, ChevronUp, ChevronDown,
  Sparkles, History, MapPin, Plus, Lock, Trash2, Tag, Mic, Volume2, Paperclip, LayoutTemplate,
  Loader, Pause
} from 'lucide-vue-next'
import EncryptionBadge from './EncryptionBadge.vue'
const GeotagModal = defineAsyncComponent(() => import('./GeotagModal.vue'))
import EditorToolbar from './EditorToolbar.vue'
import EditorStatusBar from './EditorStatusBar.vue'
import EditorContextMenu from './EditorContextMenu.vue'
import TagList from '../tags/TagList.vue'
import MediaViewer from '../media/MediaViewer.vue'
import TemplatePicker from '../templates/TemplatePicker.vue'
import EmojiPicker from '../common/EmojiPicker.vue'
import { reverseGeocode } from '../../utils/geocoding'
import { useTemplatesStore } from '../../stores/templates'
import { setGeotag } from '../../api/geotagging'
import { aiStatus, suggestTags } from '../../api/ai'
import { encryptText, decryptText } from '../../api/encryption'
import { ttsApi } from '../../api/tts'
import { useDragDrop } from '../../composables/useDragDrop'
import { useLocalStorage } from '@vueuse/core'
import { useMarkdownPreview } from '../../composables/useMarkdownPreview'
import { useEditorHistory } from '../../composables/useEditorHistory'
import { useFindReplace } from '../../composables/useFindReplace'
import { useAiTools } from '../../composables/useAiTools'
import { useAttachments } from '../../composables/useAttachments'

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

// ── Composables (early — no dependencies on later functions) ──
const { undoStack, redoStack, pushHistory, doUndo, doRedo } = useEditorHistory(body, textarea)
const { showFind, findQuery, replaceQuery, findIndex, findCount, jumpToMatch, replaceOne, replaceAll } = useFindReplace(body, textarea, pushHistory)
const { attachments, loadAttachments, handleFileUpload, removeAttachment, runOcrTool: _runOcrTool } = useAttachments(
  () => hasEntry.value,
  () => ui.editingEntryId ?? null,
  () => entries.refreshAll(),
)
function runOcrTool(mediaId: number) {
  return _runOcrTool(mediaId, body, pushHistory, markDirty)
}
const fileInput = ref<HTMLInputElement | null>(null)

// Drag & Drop
const { isDragging, handlers: dragHandlers } = useDragDrop()

function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e) }

// ── Cached selection (preserved when editor loses focus) ──
const cachedSelStart = ref(0)
const cachedSelEnd = ref(0)
let selCacheTimer: ReturnType<typeof setTimeout> | null = null

function cacheSelection() {
  const el = textarea.value
  if (el) {
    cachedSelStart.value = el.selectionStart
    cachedSelEnd.value = el.selectionEnd
  }
}

function startSelCache() {
  // Cache on blur with a short delay so click handlers in drawer can still read it
  selCacheTimer = setTimeout(cacheSelection, 0)
}

function clearSelCache() {
  if (selCacheTimer) { clearTimeout(selCacheTimer); selCacheTimer = null }
  cacheSelection() // cache immediately on focus too
}

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

// ── Undo / Redo history ── (extracted to useEditorHistory composable)
// ── Find & Replace ── (extracted to useFindReplace composable)

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

const { renderedPreview } = useMarkdownPreview(() => body.value)

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
        const store = useTemplatesStore()
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
    // Don't dismiss while AI is running
    if (aiLoading.value) return
    // If AI result panel is showing, clear it (dismisses without action)
    if (aiResult.value) {
      clearAiResult()
    }
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
  contextMenuPos.value = { x: e.clientX, y: e.clientY - 12 }
  showContextMenu.value = true
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return

  // Close active overlays in priority order
  if (showTemplates.value) { showTemplates.value = false; return }
  if ((showContextMenu.value || aiResult.value) && !aiLoading.value) { clearAiResult(); return }
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
  getSelection, applyToSelection,
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
  const start = document.activeElement === el ? el.selectionStart : cachedSelStart.value
  const end = document.activeElement === el ? el.selectionEnd : cachedSelEnd.value
  return body.value.slice(start, end).trim()
}

function applyToSelection(newText: string) {
  const el = textarea.value
  if (!el) return
  const focused = document.activeElement === el
  const start = focused ? el.selectionStart : cachedSelStart.value
  const end = focused ? el.selectionEnd : cachedSelEnd.value
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

async function onDropFiles(e: DragEvent) {
  const accepted = dragHandlers.onDrop(e)
  if (!accepted?.length) return
  // Auto-save entry first if new
  if (!hasEntry.value) {
    await save()
    if (!hasEntry.value) return
  }
  await handleFileUpload({ length: accepted.length, item: (i: number) => accepted[i] } as any)
}

// ── Attachments ── (extracted to useAttachments composable)

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

// handleFileUpload, removeAttachment, runOcrTool — extracted to useAttachments composable

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

// ── Inline AI tools (context menu) ── (extracted to useAiTools composable)
// runAiTool, aiResultReplace, aiResultInsert, aiResultRetry, aiResultCopy, clearAiResult — in composable

// Initialize AI tools composable (needs getSelection/applyToSelection defined above)
const {
  aiLoading, aiResult, aiResultMode, aiToneStyle,
  runAiTool, aiResultReplace, aiResultInsert, aiResultRetry, aiResultCopy, applyToneStyle, clearAiResult,
} = useAiTools(body, getSelection, applyToSelection, cachedSelStart, cachedSelEnd, textarea, pushHistory, markDirty)

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

// Active formatting detection (throttled to avoid recalculating on every keystroke)
const activeFormats = ref(new Set<string>())

function computeFormats() {
  const el = textarea.value
  if (!el) { activeFormats.value = new Set<string>(); return }
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
  activeFormats.value = s
}

// Throttle format recalculation at 200ms
import { watchThrottled } from '@vueuse/core'
watchThrottled(body, computeFormats, { throttle: 200, immediate: true })
</script>

<template>
  <div
    class="flex flex-col h-full"
    :class="[
      fullscreen ? 'fixed inset-0 z-[100] bg-editor' : '',
      focusMode ? 'bg-editor' : ''
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
        <div class="text-sm font-medium text-accent/80 flex flex-col items-center gap-1">
          <Paperclip :size="24" />
          Drop files here
        </div>
      </div>
    </Transition>
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


    <!-- Formatting toolbar -->
    <EditorToolbar
      v-if="!showPreview && !focusMode"
      :active-formats="activeFormats"
      :undo-count="undoStack.length"
      :redo-count="redoStack.length"
      :show-emoji="showEmoji"
      :show-find="showFind"
      :focus-mode="focusMode"
      :typewriter-mode="typewriterMode"
      :ui="ui"
      @action="(name: string) => { const fn = (fmt as any)[name]; if (fn) fn() }"
      @toggle-emoji="showEmoji = !showEmoji"
      @toggle-find="showFind = !showFind"
      @toggle-focus="focusMode = !focusMode"
      @toggle-typewriter="typewriterMode = !typewriterMode"
    />

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
            @focus="clearSelCache"
            @blur="startSelCache"
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
      <EditorStatusBar :stats="stats" :saving="!!saveTimer" :saved="!!body.trim()" />

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

    <!-- Context Menu / AI Result Panel -->
    <EditorContextMenu
      :visible="showContextMenu"
      :position="contextMenuPos"
      :ai-loading="aiLoading"
      :ai-result="aiResult"
      :ai-result-mode="aiResultMode"
      :ai-tone-style="aiToneStyle"
      @close="showContextMenu = false"
      @copy="copyToClipboard"
      @cut="cutToClipboard"
      @bold="fmt.bold()"
      @italic="fmt.italic()"
      @encrypt="encryptSelection()"
      @run-ai-tool="(mode: any) => runAiTool(mode)"
      @ai-result-replace="aiResultReplace"
      @ai-result-insert="aiResultInsert"
      @ai-result-retry="aiResultRetry"
      @ai-result-copy="aiResultCopy"
      @apply-tone-style="(tone: any) => applyToneStyle(tone)"
      @close-result="clearAiResult"
    />
  </div>
</template>

<style scoped>
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
