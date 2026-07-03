<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { Plus, Search, NotebookPen, Folder, FolderOpen, Inbox, FileText, FolderPlus, Check, Trash2, X } from 'lucide-vue-next'
import { useNotesStore } from '../../stores/notes'
import { useUiStore } from '../../stores/ui'
import { notesApi } from '../../api/notes'
import { tagsApi } from '../../api/tags'
import NoteListItem from './NoteListItem.vue'
import NoteEditor from './NoteEditor.vue'
import type { NoteResponse, TagResponse } from '../../types'

const store = useNotesStore()
const ui = useUiStore()

const folderFilter = ref<'all' | 'unfiled' | number>('all')
const searchQuery = ref('')
const searchResults = ref<NoteResponse[] | null>(null)
const allTags = ref<TagResponse[]>([])

// Inline "new folder" creator state
const showNewFolder = ref(false)
const newFolderName = ref('')
const folderInputRef = ref<HTMLInputElement | null>(null)

const notesToShow = computed(() => {
  const base = searchResults.value ?? store.notes
  if (folderFilter.value === 'unfiled') return base.filter((n) => n.folder_id == null)
  return base
})

async function loadTags() {
  try {
    allTags.value = await tagsApi.list()
  } catch {
    allTags.value = []
  }
}

async function applyFolderFilter() {
  searchResults.value = null
  searchQuery.value = ''
  const params =
    folderFilter.value === 'all' || folderFilter.value === 'unfiled'
      ? { limit: 100 }
      : { folder_id: folderFilter.value, limit: 100 }
  await store.fetchNotes(params)
}

function selectFolder(f: 'all' | 'unfiled' | number) {
  folderFilter.value = f
  void applyFolderFilter()
}

async function selectNote(id: number) {
  await store.selectNote(id)
}

async function newNote() {
  // A folder is required — use the active one, else the first available.
  let folderId: number | undefined
  if (typeof folderFilter.value === 'number') folderId = folderFilter.value
  else if (store.folders.length) folderId = store.folders[0].id
  if (folderId == null) {
    alert('Please create a folder first — every note belongs to a folder.')
    return
  }
  const n = await store.createNote({ title: '', body: '', folder_id: folderId })
  await applyFolderFilter()
  await store.fetchFolders()
  await store.selectNote(n.id)
}

async function onDeleted() {
  await store.fetchFolders()
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
  if (!confirm(`Delete folder "${name}"? Its notes will be un-filed, not deleted.`)) return
  await store.deleteFolder(id)
  if (folderFilter.value === id) selectFolder('all')
}

// Debounced search (notes-only FTS via /notes/search).
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
      searchResults.value = res.items
    } catch {
      searchResults.value = []
    }
  }, 300)
})

onMounted(async () => {
  ui.setView('notes')
  await Promise.all([applyFolderFilter(), store.fetchFolders(), loadTags()])
})
</script>

<template>
  <div class="flex h-full bg-surface">
    <!-- Left: folders + note list -->
    <div class="w-72 shrink-0 flex flex-col border-r border-border bg-editor/30">
      <!-- Header -->
      <div class="px-3 py-2 border-b border-border flex items-center justify-between">
        <div class="flex items-center gap-1.5">
          <NotebookPen :size="14" class="text-accent" />
          <span class="text-sm font-semibold text-text-primary">Notes</span>
          <span class="text-[10px] text-text-muted">({{ notesToShow.length }})</span>
        </div>
        <button
          @click="newNote"
          class="flex items-center gap-1 px-2 py-1 rounded bg-accent text-white text-[11px] font-medium hover:bg-accent/90 transition-colors"
          title="New note"
        >
          <Plus :size="12" /> New
        </button>
      </div>

      <!-- Search -->
      <div class="px-2 py-1.5 border-b border-border">
        <div class="relative">
          <Search :size="12" class="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            v-model="searchQuery"
            placeholder="Search notes…"
            class="w-full pl-7 pr-2 py-1 bg-surface-hover border border-border rounded text-[11px] text-text-primary outline-none focus:border-accent"
          />
        </div>
      </div>

      <!-- Library + Folders -->
      <div class="px-1.5 py-1.5 border-b border-border">
        <!-- Library (system views) -->
        <div class="px-1 pt-0.5 pb-1">
          <span class="text-[9px] font-bold uppercase tracking-wider text-text-muted">Library</span>
        </div>
        <button
          class="folder-btn"
          :class="folderFilter === 'all' ? 'active' : ''"
          @click="selectFolder('all')"
        >
          <Inbox :size="12" /> <span class="flex-1 text-left">All Notes</span>
        </button>
        <button
          class="folder-btn"
          :class="folderFilter === 'unfiled' ? 'active' : ''"
          @click="selectFolder('unfiled')"
        >
          <FileText :size="12" /> <span class="flex-1 text-left">Unfiled</span>
        </button>

        <!-- Folders (user) -->
        <div class="flex items-center justify-between px-1 pt-2 pb-1">
          <span class="text-[9px] font-bold uppercase tracking-wider text-text-muted">Folders</span>
          <button
            @click="startNewFolder"
            class="p-0.5 rounded text-text-muted hover:text-accent hover:bg-surface-hover transition-colors"
            title="New folder"
          >
            <FolderPlus :size="12" />
          </button>
        </div>

        <!-- Inline new-folder input -->
        <div v-if="showNewFolder" class="flex items-center gap-1 px-1 pb-1">
          <input
            ref="folderInputRef"
            v-model="newFolderName"
            placeholder="Folder name…"
            class="flex-1 px-2 py-1 bg-surface-hover border border-border rounded text-[11px] text-text-primary outline-none focus:border-accent"
            @keydown.enter="createFolder"
            @keydown.esc="cancelNewFolder"
          />
          <button
            @click="createFolder"
            class="p-1 rounded bg-accent text-white hover:bg-accent/90 transition-colors"
            title="Create folder"
          >
            <Check :size="11" />
          </button>
          <button
            @click="cancelNewFolder"
            class="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
            title="Cancel"
          >
            <X :size="11" />
          </button>
        </div>

        <div
          v-if="!store.folders.length && !showNewFolder"
          class="px-2 py-1.5 text-[10px] text-text-muted italic"
        >
          No folders yet — click + to create one.
        </div>

        <div
          v-for="f in store.folders"
          :key="f.id"
          class="flex items-center gap-0.5 group"
        >
          <button
            class="folder-btn flex-1"
            :class="folderFilter === f.id ? 'active' : ''"
            @click="selectFolder(f.id)"
          >
            <component :is="folderFilter === f.id ? FolderOpen : Folder" :size="12" />
            <span class="flex-1 text-left truncate">{{ f.name }}</span>
            <span class="text-[9px] text-text-muted">{{ f.note_count }}</span>
          </button>
          <button
            @click="removeFolder(f.id, f.name)"
            class="p-1 rounded text-text-muted hover:text-red-400 hover:bg-surface-hover transition-colors opacity-0 group-hover:opacity-100"
            title="Delete folder"
          >
            <Trash2 :size="11" />
          </button>
        </div>
      </div>

      <!-- Note list -->
      <div class="flex-1 overflow-y-auto custom-scrollbar p-1.5 space-y-1">
        <div v-if="store.loading" class="text-center text-[11px] text-text-muted py-6">Loading…</div>
        <div
          v-else-if="!notesToShow.length"
          class="flex flex-col items-center text-center text-[11px] text-text-muted py-10 px-4 gap-2"
        >
          <NotebookPen :size="22" class="opacity-40" />
          <span>No notes here yet.</span>
          <button @click="newNote" class="text-accent hover:underline">Create your first note</button>
        </div>
        <NoteListItem
          v-for="n in notesToShow"
          v-else
          :key="n.id"
          :note="n"
          :folders="store.folders"
          :active="store.currentNote?.id === n.id"
          @select="selectNote(n.id)"
        />
      </div>
    </div>

    <!-- Right: editor or empty state -->
    <div class="flex-1 min-w-0 flex flex-col">
      <NoteEditor
        v-if="store.currentNote"
        :key="store.currentNote.id"
        :note="store.currentNote"
        :folders="store.folders"
        :all-tags="allTags"
        @deleted="onDeleted"
        @tag-created="onTagCreated"
      />
      <div v-else class="flex-1 flex flex-col items-center justify-center text-text-muted gap-2">
        <NotebookPen :size="32" class="opacity-40" />
        <p class="text-xs">Select a note or create a new one to get started.</p>
        <button
          @click="newNote"
          class="mt-1 flex items-center gap-1 px-3 py-1.5 rounded bg-accent text-white text-xs font-medium hover:bg-accent/90 transition-colors"
        >
          <Plus :size="12" /> New note
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.folder-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.3rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 11px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.folder-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.folder-btn.active {
  background: rgba(88, 117, 247, 0.15);
  color: var(--color-accent);
}
</style>
