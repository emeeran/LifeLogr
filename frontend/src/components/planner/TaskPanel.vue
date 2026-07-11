<script setup lang="ts">
/** TaskPanel — task lists, inline task creation, completion, subtasks. */
import { computed, onMounted, ref } from 'vue'
import { usePlannerStore } from '../../stores/planner'
import type { TaskResponse, TaskPriority } from '../../types'
import {
  Plus, Check, Trash2, ListPlus, ChevronRight, Flag, Circle, CheckCircle2, AlertCircle, CheckCircle,
} from 'lucide-vue-next'

const store = usePlannerStore()

const newTitle = ref('')
const newPriority = ref<TaskPriority | ''>('')
const newListName = ref('')
const addingList = ref(false)
const expanded = ref<Set<number>>(new Set())
const toast = ref<{ type: 'success' | 'error'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

onMounted(async () => {
  await Promise.all([store.fetchTaskLists(), store.fetchTasks()])
})

const PRIORITY_COLORS: Record<string, string> = {
  high: 'text-red-500',
  medium: 'text-amber-500',
  low: 'text-sky-500',
}

async function addTask() {
  const title = newTitle.value.trim()
  if (!title) return
  try {
    await store.createTask({
      title,
      list_id: store.selectedListId,
      priority: newPriority.value || null,
    })
    newTitle.value = ''
    newPriority.value = ''
  } catch {
    showToast('error', 'Could not add task')
  }
}

const subtaskInputs = ref<Record<number, string>>({})
async function addSubtask(parent: TaskResponse) {
  const title = (subtaskInputs.value[parent.id] || '').trim()
  if (!title) return
  try {
    await store.createTask({ title, parent_id: parent.id, list_id: parent.list_id })
    subtaskInputs.value[parent.id] = ''
    expanded.value.add(parent.id)
  } catch {
    showToast('error', 'Could not add subtask')
  }
}

async function addList() {
  const name = newListName.value.trim()
  if (!name) return
  try {
    await store.createList(name)
    newListName.value = ''
    addingList.value = false
  } catch {
    showToast('error', 'Could not create list')
  }
}

function toggleExpand(id: number) {
  expanded.value.has(id) ? expanded.value.delete(id) : expanded.value.add(id)
}

const incompleteCount = computed(() => store.tasks.reduce((n, t) => n + (t.is_completed ? 0 : 1), 0))
</script>

<template>
  <div class="h-full flex">
    <!-- Lists sidebar -->
    <aside class="w-44 shrink-0 border-r border-border overflow-y-auto p-3 space-y-1">
      <button @click="store.selectedListId = null; store.fetchTasks()"
        class="w-full text-left px-2.5 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer"
        :class="store.selectedListId === null ? 'bg-accent/10 text-accent' : 'text-text-secondary hover:bg-surface-hover'">
        All tasks
        <span class="float-right text-text-muted">{{ incompleteCount }}</span>
      </button>
      <button v-for="l in store.taskLists" :key="l.id"
        @click="store.selectedListId = l.id; store.fetchTasks()"
        class="w-full flex items-center justify-between gap-2 text-left px-2.5 py-1.5 rounded-md text-[12px] transition-colors cursor-pointer"
        :class="store.selectedListId === l.id ? 'bg-accent/10 text-accent' : 'text-text-secondary hover:bg-surface-hover'">
        <span class="flex items-center gap-1.5 truncate">
          <span class="w-2 h-2 rounded-full shrink-0" :style="{ background: l.color || 'var(--color-accent)' }" />
          <span class="truncate">{{ l.name }}</span>
        </span>
        <Trash2 :size="11" class="opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-danger shrink-0"
          @click.stop="store.removeList(l.id)" />
      </button>

      <div class="pt-2">
        <button v-if="!addingList" @click="addingList = true"
          class="w-full inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11.5px] text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer">
          <ListPlus :size="12" /> New list
        </button>
        <div v-else class="flex gap-1">
          <input v-model="newListName" @keyup.enter="addList" placeholder="List name"
            class="flex-1 min-w-0 px-2 py-1 bg-surface-hover border border-border rounded text-[11px] text-text-primary outline-none focus:border-accent" />
          <button @click="addList" class="text-accent hover:text-accent-hover p-1"><Check :size="13" /></button>
        </div>
      </div>
    </aside>

    <!-- Task area -->
    <div class="flex-1 overflow-y-auto p-5 space-y-3 relative">
      <!-- Add task -->
      <div class="flex items-center gap-2 bg-surface rounded-lg p-2 border border-border focus-within:border-accent/50 transition-colors">
        <Circle :size="15" class="text-text-muted shrink-0 ml-1" />
        <input v-model="newTitle" @keyup.enter="addTask()" placeholder="Add a task…"
          class="flex-1 bg-transparent text-[13px] text-text-primary outline-none placeholder:text-text-muted" />
        <select v-model="newPriority"
          class="px-2 py-1 bg-surface-hover border border-border rounded text-[11px] text-text-secondary outline-none cursor-pointer">
          <option value="">No priority</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <button @click="addTask()" :disabled="!newTitle.trim()"
          class="inline-flex items-center gap-1 px-2.5 py-1 bg-accent text-white text-[11.5px] rounded hover:bg-accent-hover disabled:opacity-40 transition-colors cursor-pointer">
          <Plus :size="12" /> Add
        </button>
      </div>

      <!-- Show completed toggle -->
      <div class="flex items-center justify-end">
        <label class="inline-flex items-center gap-1.5 text-[11px] text-text-muted cursor-pointer select-none">
          <input type="checkbox" v-model="store.showCompleted" @change="store.fetchTasks()" class="accent-[var(--color-accent)]" />
          Show completed
        </label>
      </div>

      <!-- Loading / empty / list -->
      <div v-if="store.tasksLoading" class="text-center py-10 text-text-muted text-[13px]">Loading tasks…</div>
      <div v-else-if="store.tasks.length === 0"
        class="text-center py-12 rounded-lg border border-dashed border-border bg-surface/50">
        <p class="text-[13px] text-text-secondary">No tasks here yet.</p>
        <p class="text-[11px] text-text-muted mt-1">Add one above to get started.</p>
      </div>
      <div v-else class="space-y-1.5">
        <div v-for="t in store.tasks" :key="t.id" class="bg-surface rounded-lg border border-border">
          <!-- Top-level row -->
          <div class="flex items-center gap-2 px-3 py-2">
            <button @click="store.toggleComplete(t)" :title="t.is_completed ? 'Mark incomplete' : 'Mark complete'"
              class="shrink-0 cursor-pointer text-text-muted hover:text-accent transition-colors">
              <CheckCircle2 v-if="t.is_completed" :size="16" class="text-accent" />
              <Circle v-else :size="16" />
            </button>
            <button v-if="t.subtasks.length" @click="toggleExpand(t.id)"
              class="shrink-0 text-text-muted hover:text-text-primary cursor-pointer transition-transform"
              :class="expanded.has(t.id) ? 'rotate-90' : ''">
              <ChevronRight :size="14" />
            </button>
            <span v-else class="w-3.5 shrink-0"></span>
            <span class="flex-1 text-[13px] truncate" :class="t.is_completed ? 'line-through text-text-muted' : 'text-text-primary'">
              {{ t.title }}
            </span>
            <Flag v-if="t.priority" :size="12" class="shrink-0" :class="PRIORITY_COLORS[t.priority]" />
            <button @click="toggleExpand(t.id); subtaskInputs[t.id] = ''"
              class="shrink-0 p-1 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors cursor-pointer" title="Add subtask">
              <Plus :size="12" />
            </button>
            <button @click="store.removeTask(t.id)"
              class="shrink-0 p-1 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors cursor-pointer" title="Delete">
              <Trash2 :size="12" />
            </button>
          </div>

          <!-- Subtask add input -->
          <div v-if="expanded.has(t.id)" class="px-3 pb-2 pl-10 space-y-1">
            <div v-for="s in t.subtasks" :key="s.id" class="flex items-center gap-2 py-0.5">
              <button @click="store.toggleComplete(s)" class="shrink-0 text-text-muted hover:text-accent cursor-pointer">
                <CheckCircle v-if="s.is_completed" :size="13" class="text-accent" />
                <Circle v-else :size="13" />
              </button>
              <span class="flex-1 text-[12px] truncate" :class="s.is_completed ? 'line-through text-text-muted' : 'text-text-secondary'">
                {{ s.title }}
              </span>
              <button @click="store.removeTask(s.id)"
                class="p-0.5 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="11" /></button>
            </div>
            <div class="flex items-center gap-1.5 pt-1">
              <Plus :size="12" class="text-text-muted" />
              <input v-model="subtaskInputs[t.id]" @keyup.enter="addSubtask(t)" placeholder="Add a subtask…"
                class="flex-1 bg-transparent text-[12px] text-text-secondary outline-none placeholder:text-text-muted" />
              <button v-if="subtaskInputs[t.id]?.trim()" @click="addSubtask(t)" class="text-accent text-[11px] hover:text-accent-hover">
                Add
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Toast -->
      <Transition name="toast">
        <div v-if="toast"
          class="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-3.5 py-2 rounded-lg border text-[12px] shadow-lg z-50"
          :class="toast.type === 'success'
            ? 'bg-green-900/90 border-green-700 text-green-100'
            : 'bg-red-900/90 border-red-700 text-red-100'">
          <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
          <AlertCircle v-else :size="14" />
          {{ toast.message }}
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 10px); }
</style>
