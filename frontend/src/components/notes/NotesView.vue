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
  Plus,
  Search,
  NotebookPen,
  Folder,
  FolderOpen,
  FileText,
  FolderPlus,
  Check,
  Trash2,
  X,
  ChevronRight,
  Pin,
  Lock,
  Inbox,
  Upload,
  Pencil,
} from 'lucide-vue-next'
import { useLocalStorage } from '@vueuse/core'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { useNotesStore } from '../../stores/notes'
import { useUiStore } from '../../stores/ui'
import { notesApi } from '../../api/notes'
import { pickFile } from '../../utils/fileDialog'
import { tagsApi } from '../../api/tags'
import NoteEditor from './NoteEditor.vue'
import type { NoteListItem, NoteFolderResponse, TagResponse } from '../../types'

const store = useNotesStore()
const ui = useUiStore()

const searchQuery = ref('')
const searchResults = ref<NoteListItem[] | null>(null)
const allTags = ref<TagResponse[]>([])

// Inline "new notebook" creator state. newFolderParent is the folder the new
// sub-notebook is created under (null = top level).
const showNewFolder = ref(false)
const newFolderName = ref('')
const newFolderParent = ref<number | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)

// Inline note rename state (one leaf edited at a time).
const editingNoteId = ref<number | null>(null)
const editingNoteTitle = ref('')
const renameNoteInputRef = ref<HTMLInputElement | null>(null)

// Resizable tree rail (persisted). Drag the strip between tree and editor.
const railWidth = useLocalStorage<number>('lifelogr-notes-rail-width', 288)
const railDragging = ref(false)
function onRailMousedown(e: MouseEvent) {
  e.preventDefault()
  railDragging.value = true
  const startX = e.clientX
  const startW = railWidth.value
  function move(ev: MouseEvent) {
    railWidth.value = Math.min(
      560,
      Math.max(200, startW + (ev.clientX - startX)),
    )
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

const unfiledNotes = computed(() =>
  sortedNotes(store.notes.filter((n) => n.folder_id == null)),
)
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
  kind:
    | 'header'
    | 'tree-row'
    | 'section'
    | 'newfolder'
    | 'empty'
    | 'empty-folder'
    | 'leaf'
  text?: string
  key?: string
  label?: string
  icon?: 'inbox' | 'file' | 'folder' | 'folderopen'
  count?: number
  expanded?: boolean
  folderId?: number
  folderName?: string
  note?: NoteListItem | null
  depth?: number
}

// Folder hierarchy: the store holds a flat list, but folders carry parent_id.
// Group by parent so notebooks can nest (Obsidian-style, arbitrary depth).
const foldersByParent = computed(() => {
  const m = new Map<number | null, NoteFolderResponse[]>()
  for (const f of store.folders) {
    const arr = m.get(f.parent_id) ?? []
    arr.push(f)
    m.set(f.parent_id, arr)
  }
  return m
})

// depth-based left indent for nested rows.
function rowIndent(depth = 0) {
  return { paddingLeft: `${6 + depth * 12}px` }
}

// Recursively flatten a folder + its sub-folders + notes into virtualizable rows.
function emitFolder(out: TreeItem[], f: NoteFolderResponse, depth: number) {
  const k = String(f.id)
  out.push({
    kind: 'tree-row',
    key: k,
    label: f.name,
    icon: isExpanded(k) ? 'folderopen' : 'folder',
    count: f.note_count,
    expanded: isExpanded(k),
    folderId: f.id,
    folderName: f.name,
    depth,
  })
  if (!isExpanded(k)) return
  const kids = foldersByParent.value.get(f.id) ?? []
  for (const c of kids) emitFolder(out, c, depth + 1)
  if (showNewFolder.value && newFolderParent.value === f.id) {
    out.push({ kind: 'newfolder', depth: depth + 1 })
  }
  const here = notesIn(f.id)
  if (!kids.length && !here.length)
    out.push({ kind: 'empty-folder', depth: depth + 1 })
  else
    for (const n of here) out.push({ kind: 'leaf', note: n, depth: depth + 1 })
}

const flatTree = computed<TreeItem[]>(() => {
  if (searchResults.value) {
    const out: TreeItem[] = [
      { kind: 'header', text: `Results · ${searchResults.value.length}` },
    ]
    if (!searchResults.value.length)
      out.push({
        kind: 'empty',
        text: `No notes match “${searchQuery.value}”.`,
        depth: 1,
      })
    else
      for (const n of searchResults.value)
        out.push({ kind: 'leaf', note: n, depth: 1 })
    return out
  }
  const out: TreeItem[] = []
  out.push({
    kind: 'tree-row',
    key: 'all',
    label: 'All Notes',
    icon: 'inbox',
    count: allNotes.value.length,
    expanded: isExpanded('all'),
    depth: 0,
  })
  if (isExpanded('all')) {
    if (!allNotes.value.length)
      out.push({ kind: 'empty', text: 'No notes yet.', depth: 1 })
    else
      for (const n of allNotes.value)
        out.push({ kind: 'leaf', note: n, depth: 1 })
  }
  out.push({
    kind: 'tree-row',
    key: 'unfiled',
    label: 'Unfiled',
    icon: 'file',
    count: unfiledNotes.value.length,
    expanded: isExpanded('unfiled'),
    depth: 0,
  })
  if (isExpanded('unfiled')) {
    if (!unfiledNotes.value.length)
      out.push({ kind: 'empty', text: 'Nothing unfiled.', depth: 1 })
    else
      for (const n of unfiledNotes.value)
        out.push({ kind: 'leaf', note: n, depth: 1 })
  }
  out.push({ kind: 'section' })
  if (showNewFolder.value && newFolderParent.value === null)
    out.push({ kind: 'newfolder', depth: 0 })
  const roots = foldersByParent.value.get(null) ?? []
  if (!roots.length && !showNewFolder.value)
    out.push({ kind: 'empty', text: 'No notebooks — click + to create one.' })
  for (const f of roots) emitFolder(out, f, 0)
  return out
})
const treeScrollEl = ref<HTMLElement | null>(null)
const treeVirtualizer = useVirtualizer(
  computed(() => ({
    count: flatTree.value.length,
    getScrollElement: () => treeScrollEl.value,
    estimateSize: (i: number) =>
      flatTree.value[i].kind === 'leaf'
        ? 24
        : flatTree.value[i].kind === 'newfolder'
          ? 34
          : 26,
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
    if (!expanded.value.has(key))
      expanded.value = new Set([...expanded.value, key])
  },
)

async function newNote() {
  // Default to the selected note's notebook, else the first available.
  let folderId: number | undefined
  if (store.currentNote?.folder_id != null)
    folderId = store.currentNote.folder_id
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

// Import a single Markdown (.md) file as a new note, then open it.
const importingMd = ref(false)
async function importMarkdown() {
  const file = await pickFile({ accept: '.md,.markdown' })
  if (!file) return
  importingMd.value = true
  try {
    const res = await notesApi.importMarkdownFile(file)
    if (!res.imported || res.note_id == null) {
      alert('Could not import that file — is it a valid Markdown note?')
      return
    }
    await Promise.all([store.fetchNotes({ limit: 100 }), store.fetchFolders()])
    await store.selectNote(res.note_id)
  } catch (e: unknown) {
    alert(`Import failed: ${e instanceof Error ? e.message : e}`)
  } finally {
    importingMd.value = false
  }
}

async function onTagCreated() {
  await loadTags()
}

function startNewFolder(parentId: number | null = null) {
  newFolderParent.value = parentId
  newFolderName.value = ''
  showNewFolder.value = true
  // Make sure the target parent is expanded so the inline input is visible.
  if (parentId != null) {
    const key = String(parentId)
    if (!expanded.value.has(key))
      expanded.value = new Set([...expanded.value, key])
  }
  nextTick(() => folderInputRef.value?.focus())
}

async function createFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  try {
    await store.createFolder(name, newFolderParent.value)
    showNewFolder.value = false
    newFolderName.value = ''
    newFolderParent.value = null
  } catch {
    /* store surfaces error */
  }
}

function cancelNewFolder() {
  showNewFolder.value = false
  newFolderName.value = ''
  newFolderParent.value = null
}

// ── Inline note rename / delete (on each leaf) ──
function startRenameNote(n: NoteListItem) {
  editingNoteId.value = n.id
  editingNoteTitle.value = n.title ?? ''
  nextTick(() => renameNoteInputRef.value?.focus())
}
function cancelRenameNote() {
  editingNoteId.value = null
  editingNoteTitle.value = ''
}
async function commitRenameNote() {
  const id = editingNoteId.value
  const name = editingNoteTitle.value.trim()
  editingNoteId.value = null
  if (id == null || !name) return
  try {
    await store.updateNote(id, { title: name })
  } catch {
    /* store surfaces error */
  }
}
async function deleteNoteInline(n: NoteListItem) {
  const label = n.title?.trim() || 'this untitled note'
  if (!confirm(`Delete “${label}”? It can be restored later.`)) return
  try {
    await store.deleteNote(n.id)
  } catch {
    /* store surfaces error */
  }
}

async function removeFolder(id: number, name: string) {
  if (
    !confirm(
      `Delete notebook "${name}"? Its notes will be un-filed, not deleted.`,
    )
  )
    return
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

onMounted(async () => {
  ui.setView('notes')
  await Promise.all([
    store.fetchNotes({ limit: 100 }),
    store.fetchFolders(),
    loadTags(),
  ])
  // Land on the most-recently-edited note (pinned first) instead of creating
  // an empty note every time Notes opens — that littered the DB with untitled
  // notes. If there are none yet, the empty-state panel (with its "New note"
  // button) is shown.
  const target = sortedNotes(store.notes)[0]
  if (target) await store.selectNote(target.id)
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
        <span class="flex-1" />
        <button
          class="rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-accent disabled:opacity-50"
          :disabled="importingMd"
          :title="importingMd ? 'Importing…' : 'Import a Markdown (.md) note'"
          @click="importMarkdown"
        >
          <Upload :size="13" />
        </button>
      </div>

      <!-- Search -->
      <div class="border-b border-border px-2 py-2">
        <div class="relative">
          <Search
            :size="12"
            class="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
          />
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
      <div
        ref="treeScrollEl"
        class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-1.5 py-2"
      >
        <div
          :style="{
            height: `${treeVirtualizer.getTotalSize()}px`,
            position: 'relative',
          }"
        >
          <div
            v-for="vr in treeVirtualizer.getVirtualItems()"
            :key="String(vr.key)"
            :style="{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${vr.start}px)`,
            }"
          >
            <!-- header (search results count) -->
            <div v-if="flatTree[vr.index].kind === 'header'" class="px-1 pb-1">
              <span
                class="text-[9px] font-bold uppercase tracking-wider text-text-muted"
                >{{ flatTree[vr.index].text }}</span
              >
            </div>
            <!-- tree-row (expandable group) -->
            <div
              v-else-if="flatTree[vr.index].kind === 'tree-row'"
              class="group flex items-center gap-0.5"
              :style="rowIndent(flatTree[vr.index].depth)"
            >
              <button
                class="tree-row flex-1"
                @click="toggleExpand(flatTree[vr.index].key!)"
              >
                <ChevronRight
                  :size="13"
                  class="chevron shrink-0"
                  :class="{ open: flatTree[vr.index].expanded }"
                />
                <component :is="iconFor(flatTree[vr.index].icon!)" :size="12" />
                <span class="flex-1 truncate text-left">{{
                  flatTree[vr.index].label
                }}</span>
                <span class="count">{{ flatTree[vr.index].count }}</span>
              </button>
              <button
                v-if="flatTree[vr.index].folderId != null"
                @click="startNewFolder(flatTree[vr.index].folderId!)"
                class="rounded p-1 text-text-muted opacity-0 transition-all hover:bg-surface-hover hover:text-accent group-hover:opacity-100"
                title="New sub-notebook"
              >
                <FolderPlus :size="11" />
              </button>
              <button
                v-if="flatTree[vr.index].folderId != null"
                @click="
                  removeFolder(
                    flatTree[vr.index].folderId!,
                    flatTree[vr.index].folderName!,
                  )
                "
                class="rounded p-1 text-text-muted opacity-0 transition-all hover:bg-surface-hover hover:text-red-400 group-hover:opacity-100"
                title="Delete notebook"
              >
                <Trash2 :size="11" />
              </button>
            </div>
            <!-- section (Notebooks label + new-folder button) -->
            <div
              v-else-if="flatTree[vr.index].kind === 'section'"
              class="flex items-center justify-between px-1 pb-1 pt-3"
            >
              <span
                class="text-[9px] font-bold uppercase tracking-wider text-text-muted"
                >Notebooks</span
              >
              <button
                @click="startNewFolder(null)"
                class="rounded p-0.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-accent"
                title="New notebook"
              >
                <FolderPlus :size="12" />
              </button>
            </div>
            <!-- inline new-notebook / sub-notebook input -->
            <div
              v-else-if="flatTree[vr.index].kind === 'newfolder'"
              class="flex items-center gap-1 px-1 pb-1"
              :style="rowIndent(flatTree[vr.index].depth)"
            >
              <input
                ref="folderInputRef"
                v-model="newFolderName"
                placeholder="Notebook name…"
                class="flex-1 rounded border border-border bg-surface-hover px-2 py-1 text-[11px] text-text-primary outline-none focus:border-accent"
                @keydown.enter="createFolder"
                @keydown.esc="cancelNewFolder"
              />
              <button
                @click="createFolder"
                class="rounded bg-accent p-1 text-white transition-colors hover:bg-accent/90"
                title="Create"
              >
                <Check :size="11" />
              </button>
              <button
                @click="cancelNewFolder"
                class="rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
                title="Cancel"
              >
                <X :size="11" />
              </button>
            </div>
            <!-- empty state -->
            <div
              v-else-if="flatTree[vr.index].kind === 'empty'"
              class="px-2 py-1.5 text-[10px] italic text-text-muted"
              :style="rowIndent(flatTree[vr.index].depth)"
            >
              {{ flatTree[vr.index].text }}
            </div>
            <!-- empty folder (with add-note action) -->
            <div
              v-else-if="flatTree[vr.index].kind === 'empty-folder'"
              class="px-2 py-1.5 text-[10px] italic text-text-muted"
              :style="rowIndent(flatTree[vr.index].depth)"
            >
              Empty —
              <button class="text-accent hover:underline" @click="newNote">
                add a note
              </button>
            </div>
            <!-- note leaf: click to open · double-click to rename · hover for edit/delete -->
            <div
              v-else
              class="note-leaf group"
              :class="{
                active: store.currentNote?.id === flatTree[vr.index].note!.id,
              }"
              :style="rowIndent(flatTree[vr.index].depth)"
            >
              <input
                v-if="editingNoteId === flatTree[vr.index].note!.id"
                ref="renameNoteInputRef"
                v-model="editingNoteTitle"
                class="rename-note-input"
                @keydown.enter.prevent="commitRenameNote"
                @keydown.esc.prevent="cancelRenameNote"
                @blur="commitRenameNote"
              />
              <template v-else>
                <button
                  class="note-leaf-main"
                  :title="leafLabel(flatTree[vr.index].note!)"
                  @click="selectNote(flatTree[vr.index].note!.id)"
                  @dblclick="startRenameNote(flatTree[vr.index].note!)"
                >
                  <FileText
                    :size="12"
                    class="shrink-0"
                    :class="
                      flatTree[vr.index].note!.is_pinned
                        ? 'text-accent'
                        : 'text-text-muted'
                    "
                  />
                  <span class="flex-1 truncate">{{
                    leafLabel(flatTree[vr.index].note!)
                  }}</span>
                  <Pin
                    v-if="flatTree[vr.index].note!.is_pinned"
                    :size="9"
                    class="shrink-0 text-accent"
                  />
                  <Lock
                    v-if="flatTree[vr.index].note!.is_encrypted"
                    :size="9"
                    class="shrink-0 text-text-muted"
                  />
                </button>
                <button
                  class="note-leaf-action"
                  title="Rename"
                  @click.stop="startRenameNote(flatTree[vr.index].note!)"
                >
                  <Pencil :size="11" />
                </button>
                <button
                  class="note-leaf-action"
                  title="Delete note"
                  @click.stop="deleteNoteInline(flatTree[vr.index].note!)"
                >
                  <Trash2 :size="11" />
                </button>
              </template>
            </div>
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
      <div
        v-else
        class="flex flex-1 flex-col items-center justify-center gap-3 text-text-muted"
      >
        <div
          class="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/10"
        >
          <NotebookPen :size="28" class="text-accent/60" />
        </div>
        <div class="text-center">
          <p class="text-sm font-medium text-text-secondary">
            No note selected
          </p>
          <p class="mt-0.5 text-xs">
            Pick a note from the tree or create a new one.
          </p>
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
  transition:
    background-color 0.15s,
    color 0.15s;
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
  gap: 0.2rem;
  width: 100%;
  padding: 0.22rem 0.4rem;
  border-radius: 0.375rem;
  color: var(--color-text-secondary);
  transition:
    background-color 0.15s,
    color 0.15s;
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
.note-leaf-main {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex: 1 1 auto;
  min-width: 0;
  padding: 0.06rem 0.1rem;
  background: transparent;
  border: none;
  font-size: 11.5px;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.note-leaf-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  padding: 0.15rem 0.2rem;
  border-radius: 0.25rem;
  color: var(--color-text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.15s,
    color 0.15s,
    background-color 0.15s;
}
.note-leaf:hover .note-leaf-action,
.note-leaf.active .note-leaf-action {
  opacity: 1;
}
.note-leaf-action:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}
.rename-note-input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0.1rem 0.35rem;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-accent);
  border-radius: 0.25rem;
  font-size: 11.5px;
  color: var(--color-text-primary);
  outline: none;
}
</style>
