<script setup lang="ts">
/**
 * NotesView — 2-pane notebook workspace (EPIM-style tree | editor).
 *
 * The folder rail IS the tree: notebooks expand to reveal their notes as
 * indented leaves (pinned first). "All Notes" / "Unfiled" are virtual nodes
 * that expand the same way. Selecting a leaf opens it in the editor on the
 * right. Search collapses the tree into a flat results list.
 */
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import {
  Plus, Search, NotebookPen, Folder, FolderOpen, FileText, FolderPlus,
  Check, Trash2, X, ChevronRight, Pin, Lock, Inbox,
} from 'lucide-vue-next'
import { useLocalStorage } from '@vueuse/core'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { useNotesStore } from '../../stores/notes'
import { useUiStore } from '../../stores/ui'
import { notesApi } from '../../api/notes'
import { tagsApi } from '../../api/tags'
import NoteEditor from './NoteEditor.vue'
import type { NoteListItem, TagResponse } from '../../types'

const store = useNotesStore()
const ui = useUiStore()

const searchQuery = ref('')
const searchResults = ref<NoteListItem[] | null>(null)
const allTags = ref<TagResponse[]>([])

// Inline "new notebook" creator state
const showNewFolder = ref(false)
const newFolderName = ref('')
const folderInputRef = ref<HTMLInputElement | null>(null)

// Resizable tree rail (persisted). Drag the strip between tree and editor.
const railWidth = useLocalStorage<number>('lifelogr-notes-rail-width', 288)
const railDragging = ref(false)
function onRailMousedown(e: MouseEvent) {
  e.preventDefault()
  railDragging.value = true
  const startX = e.clientX
  const startW = railWidth.value
  function move(ev: MouseEvent) {
    railWidth.value = Math.min(560, Math.max(200, startW + (ev.clientX - startX)))
  }
  function up() {
    railDragging.value = false
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', up)
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', up)
}

// Expanded tree nodes: 'all' | 'unfiled' | <folder id as string>
const expanded = ref<Set<string>>(new Set(['all']))

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  next.has(key) ? next.delete(key) : next.add(key)
  expanded.value = next
}
const isExpanded = (key: string) => expanded.value.has(key)

// Pinned-first, then most-recently-updated.
function sortedNotes(arr: NoteListItem[]): NoteListItem[] {
  return [...arr].sort((a, b) => {
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })
}

const unfiledNotes = computed(() => sortedNotes(store.notes.filter((n) => n.folder_id == null)))
const allNotes = computed(() => sortedNotes(store.notes))
function notesIn(folderId: number): NoteListItem[] {
  return sortedNotes(store.notes.filter((n) => n.folder_id === folderId))
}
function leafLabel(n: NoteListItem): string {
  return n.title?.trim() || 'Untitled note'
}

// Flatten the whole rail (search list OR the expand/collapse tree) into one
// virtualizable array so only the visible slice renders — keeps the DOM flat
// even with "All Notes" expanded over thousands of notes.
interface TreeItem {
  kind: 'header' | 'tree-row' | 'section' | 'newfolder' | 'empty' | 'empty-folder' | 'leaf'
  text?: string
  key?: string
  label?: string
  icon?: 'inbox' | 'file' | 'folder' | 'folderopen'
  count?: number
  expanded?: boolean
  folderId?: number
  folderName?: string
  note?: NoteListItem | null
}
const flatTree = computed<TreeItem[]>(() => {
  if (searchResults.value) {
    const out: TreeItem[] = [{ kind: 'header', text: `Results · ${searchResults.value.length}` }]
    if (!searchResults.value.length) out.push({ kind: 'empty', text: `No notes match “${searchQuery.value}”.` })
    else for (const n of searchResults.value) out.push({ kind: 'leaf', note: n })
    return out
  }
  const out: TreeItem[] = []
  out.push({ kind: 'tree-row', key: 'all', label: 'All Notes', icon: 'inbox', count: allNotes.value.length, expanded: isExpanded('all') })
  if (isExpanded('all')) {
    if (!allNotes.value.length) out.push({ kind: 'empty', text: 'No notes yet.' })
    else for (const n of allNotes.value) out.push({ kind: 'leaf', note: n })
  }
  out.push({ kind: 'tree-row', key: 'unfiled', label: 'Unfiled', icon: 'file', count: unfiledNotes.value.length, expanded: isExpanded('unfiled') })
  if (isExpanded('unfiled')) {
    if (!unfiledNotes.value.length) out.push({ kind: 'empty', text: 'Nothing unfiled.' })
    else for (const n of unfiledNotes.value) out.push({ kind: 'leaf', note: n })
  }
  out.push({ kind: 'section' })
  if (showNewFolder.value) out.push({ kind: 'newfolder' })
  if (!store.folders.length && !showNewFolder.value) out.push({ kind: 'empty', text: 'No notebooks — click + to create one.' })
  for (const f of store.folders) {
    const k = String(f.id)
    out.push({ kind: 'tree-row', key: k, label: f.name, icon: isExpanded(k) ? 'folderopen' : 'folder', count: f.note_count, expanded: isExpanded(k), folderId: f.id, folderName: f.name })
    if (isExpanded(k)) {
      if (!notesIn(f.id).length) out.push({ kind: 'empty-folder' })
      else for (const n of notesIn(f.id)) out.push({ kind: 'leaf', note: n })
    }
  }
  return out
})
const treeScrollEl = ref<HTMLElement | null>(null)
const treeVirtualizer = useVirtualizer(
  computed(() => ({
    count: flatTree.value.length,
    getScrollElement: () => treeScrollEl.value,
    estimateSize: (i: number) =>
      flatTree.value[i].kind === 'leaf' ? 24 : flatTree.value[i].kind === 'newfolder' ? 34 : 26,
    overscan: 10,
  })),
)
function iconFor(icon: TreeItem['icon']) {
  if (icon === 'inbox') return Inbox
  if (icon === 'folderopen') return FolderOpen
  if (icon === 'folder') return Folder
  return FileText
}

async function loadTags() {
  try {
    allTags.value = await tagsApi.list()
  } catch {
    allTags.value = []
  }
}

async function selectNote(id: number) {
  await store.selectNote(id)
}

// Keep the selected note's parent node expanded so it stays visible.
watch(
  () => store.currentNote?.id,
  () => {
    const n = store.currentNote
    if (!n) return
    const key = n.folder_id == null ? 'unfiled' : String(n.folder_id)
    if (!expanded.value.has(key)) expanded.value = new Set([...expanded.value, key])
  },
)

async function newNote() {
  // Default to the selected note's notebook, else the first available.
  let folderId: number | undefined
  if (store.currentNote?.folder_id != null) folderId = store.currentNote.folder_id
  else if (store.folders.length) folderId = store.folders[0].id
  if (folderId == null) {
    alert('Please create a notebook first — every note belongs to a notebook.')
    return
  }
  const n = await store.createNote({ title: '', body: '', folder_id: folderId })
  await store.fetchNotes({ limit: 100 })
  await store.fetchFolders()
  await store.selectNote(n.id)
  expanded.value = new Set([...expanded.value, String(folderId)])
}

async function onDeleted() {
  await Promise.all([store.fetchNotes({ limit: 100 }), store.fetchFolders()])
}

async function onTagCreated() {
  await loadTags()
}

function startNewFolder() {
  showNewFolder.value = true
  newFolderName.value = ''
  nextTick(() => folderInputRef.value?.focus())
}

async function createFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  try {
    await store.createFolder(name)
    showNewFolder.value = false
    newFolderName.value = ''
  } catch {
    /* store surfaces error */
  }
}

function cancelNewFolder() {
  showNewFolder.value = false
  newFolderName.value = ''
}

async function removeFolder(id: number, name: string) {
  if (!confirm(`Delete notebook "${name}"? Its notes will be un-filed, not deleted.`)) return
  await store.deleteFolder(id)
  await store.fetchNotes({ limit: 100 })
}

// Debounced full-text search (notes-only FTS).
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    const trimmed = q.trim()
    if (!trimmed) {
      searchResults.value = null
      return
    }
    try {
      const res = await notesApi.search(trimmed, 0, 100)
      searchResults.value = sortedNotes(res.items)
    } catch {
      searchResults.value = []
    }
  }, 300)
})

// "Always open a fresh new note when Notes loads." Requires at least one
// notebook (every note belongs to one); if there are none yet, the editor
// stays empty so you can create a notebook first.
async function openFreshNote() {
  if (!store.folders.length) return
  const folderId = store.currentNote?.folder_id ?? store.folders[0].id
  try {
    const n = await store.createNote({ title: '', body: '', folder_id: folderId })
    await store.fetchNotes({ limit: 100 })
    await store.selectNote(n.id)
    expanded.value = new Set([...expanded.value, String(folderId)])
  } catch {
    /* leave editor empty */
  }
}

onMounted(async () => {
  ui.setView('notes')
  await Promise.all([store.fetchNotes({ limit: 100 }), store.fetchFolders(), loadTags()])
  await openFreshNote()
})
</script>

<template>
  <div class="flex h-full bg-surface">
    <!-- Tree rail (notebooks → notes) — resizable -->
    <aside
      class="flex shrink-0 flex-col border-r border-border bg-editor/30"
      :style="{ width: railWidth + 'px' }"
    >
      <!-- Header -->
      <div class="flex items-center gap-1.5 border-b border-border px-3 py-2.5">
        <NotebookPen :size="15" class="text-accent" />
        <span class="text-sm font-semibold text-text-primary">Notes</span>
        <span class="text-[10px] text-text-muted">({{ store.total }})</span>
      </div>

      <!-- Search -->
      <div class="border-b border-border px-2 py-2">
        <div class="relative">
          <Search :size="12" class="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            v-model="searchQuery"
            placeholder="Search notes…"
            class="w-full rounded border border-border bg-surface-hover py-1.5 pl-7 pr-7 text-[11px] text-text-primary outline-none focus:border-accent"
          />
          <button
            v-if="searchQuery"
            @click="searchQuery = ''"
            class="absolute right-1.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
            title="Clear"
          >
            <X :size="12" />
          </button>
        </div>
      </div>

      <!-- Tree body -->
      <div ref="treeScrollEl" class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        <div :style="{ height: `${treeVirtualizer.getTotalSize()}px`, position: 'relative' }">
          <div
            v-for="vr in treeVirtualizer.getVirtualItems()"
            :key="String(vr.key)"
            :style="{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${vr.start}px)` }"
          >
            <!-- header (search results count) -->
            <div v-if="flatTree[vr.index].kind === 'header'" class="px-1 pb-1">
              <span class="text-[9px] font-bold uppercase tracking-wider text-text-muted">{{ flatTree[vr.index].text }}</span>
            </div>
            <!-- tree-row (expandable group) -->
            <div v-else-if="flatTree[vr.index].kind === 'tree-row'" class="group flex items-center gap-0.5">
              <button class="tree-row flex-1" @click="toggleExpand(flatTree[vr.index].key!)">
                <ChevronRight :size="13" class="chevron shrink-0" :class="{ open: flatTree[vr.index].expanded }" />
                <component :is="iconFor(flatTree[vr.index].icon!)" :size="12" />
                <span class="flex-1 truncate text-left">{{ flatTree[vr.index].label }}</span>
                <span class="count">{{ flatTree[vr.index].count }}</span>
              </button>
              <button
                v-if="flatTree[vr.index].folderId != null"
                @click="removeFolder(flatTree[vr.index].folderId!, flatTree[vr.index].folderName!)"
                class="rounded p-1 text-text-muted opacity-0 transition-all hover:bg-surface-hover hover:text-red-400 group-hover:opacity-100"
                title="Delete notebook"
              >
                <Trash2 :size="11" />
              </button>
            </div>
            <!-- section (Notebooks label + new-folder button) -->
            <div v-else-if="flatTree[vr.index].kind === 'section'" class="flex items-center justify-between px-1 pb-1 pt-3">
              <span class="text-[9px] font-bold uppercase tracking-wider text-text-muted">Notebooks</span>
              <button @click="startNewFolder" class="rounded p-0.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-accent" title="New notebook">
                <FolderPlus :size="12" />
              </button>
            </div>
            <!-- inline new-notebook input -->
            <div v-else-if="flatTree[vr.index].kind === 'newfolder'" class="flex items-center gap-1 px-1 pb-1">
              <input
                ref="folderInputRef"
                v-model="newFolderName"
                placeholder="Notebook name…"
                class="flex-1 rounded border border-border bg-surface-hover px-2 py-1 text-[11px] text-text-primary outline-none focus:border-accent"
                @keydown.enter="createFolder"
                @keydown.esc="cancelNewFolder"
              />
              <button @click="createFolder" class="rounded bg-accent p-1 text-white transition-colors hover:bg-accent/90" title="Create">
                <Check :size="11" />
              </button>
              <button @click="cancelNewFolder" class="rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary" title="Cancel">
                <X :size="11" />
              </button>
            </div>
            <!-- empty state -->
            <div v-else-if="flatTree[vr.index].kind === 'empty'" class="px-2 py-1.5 text-[10px] italic text-text-muted">
              {{ flatTree[vr.index].text }}
            </div>
            <!-- empty folder (with add-note action) -->
            <div v-else-if="flatTree[vr.index].kind === 'empty-folder'" class="ml-3 px-2 py-1.5 text-[10px] italic text-text-muted">
              Empty — <button class="text-accent hover:underline" @click="newNote">add a note</button>
            </div>
            <!-- note leaf -->
            <button
              v-else
              class="note-leaf ml-3"
              :class="{ active: store.currentNote?.id === flatTree[vr.index].note!.id }"
              @click="selectNote(flatTree[vr.index].note!.id)"
            >
              <FileText :size="12" class="shrink-0" :class="flatTree[vr.index].note!.is_pinned ? 'text-accent' : 'text-text-muted'" />
              <span class="flex-1 truncate">{{ leafLabel(flatTree[vr.index].note!) }}</span>
              <Pin v-if="flatTree[vr.index].note!.is_pinned" :size="9" class="shrink-0 text-accent" />
              <Lock v-if="flatTree[vr.index].note!.is_encrypted" :size="9" class="shrink-0 text-text-muted" />
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- Resize handle between tree and editor -->
    <div
      class="shrink-0 w-1 cursor-col-resize transition-colors"
      :class="railDragging ? 'bg-accent' : 'bg-border hover:bg-accent/60'"
      title="Drag to resize"
      @mousedown="onRailMousedown"
    >
      <div class="h-full w-full" :style="{ cursor: 'col-resize' }" />
    </div>

    <!-- Editor -->
    <div class="flex min-w-0 flex-1 flex-col">
      <NoteEditor
        v-if="store.currentNote"
        :key="store.currentNote.id"
        :note="store.currentNote"
        :folders="store.folders"
        :all-tags="allTags"
        @deleted="onDeleted"
        @tag-created="onTagCreated"
        @new-note="newNote"
      />
      <div v-else class="flex flex-1 flex-col items-center justify-center gap-3 text-text-muted">
        <div class="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/10">
          <NotebookPen :size="28" class="text-accent/60" />
        </div>
        <div class="text-center">
          <p class="text-sm font-medium text-text-secondary">No note selected</p>
          <p class="mt-0.5 text-xs">Pick a note from the tree or create a new one.</p>
        </div>
        <button
          @click="newNote"
          class="mt-1 flex items-center gap-1 rounded bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/90"
        >
          <Plus :size="12" /> New note
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tree-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.32rem 0.4rem;
  border-radius: 0.375rem;
  font-size: 11.5px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.tree-row:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.chevron {
  color: var(--color-text-muted);
  transition: transform 0.15s ease;
}
.chevron.open {
  transform: rotate(90deg);
}
.count {
  font-size: 9px;
  color: var(--color-text-muted);
}
.note-leaf {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.28rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 11.5px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.note-leaf:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.note-leaf.active {
  background: rgba(88, 117, 247, 0.15);
  color: var(--color-accent);
  font-weight: 500;
}
</style>
