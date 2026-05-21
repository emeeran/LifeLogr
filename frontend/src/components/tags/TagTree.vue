<script setup lang="ts">
import { onMounted } from 'vue'
import { useTagsStore } from '../../stores/tags'
import { ChevronRight, ChevronDown, Plus, Trash2, Pencil } from 'lucide-vue-next'
import { ref } from 'vue'
import type { TagResponse } from '../../types'

const tags = useTagsStore()
const expanded = ref<Set<number>>(new Set())
const showCreate = ref(false)
const newTagName = ref('')
const newTagParent = ref<number | null>(null)
const editingId = ref<number | null>(null)
const editingName = ref('')

onMounted(() => tags.fetchTree())

function toggle(id: number) {
  if (expanded.value.has(id)) expanded.value.delete(id)
  else expanded.value.add(id)
}

async function createTag() {
  if (!newTagName.value.trim()) return
  await tags.createTag({ name: newTagName.value, parent_id: newTagParent.value })
  newTagName.value = ''
  showCreate.value = false
}

async function deleteTag(id: number) {
  await tags.deleteTag(id)
}

function startEdit(tag: TagResponse) {
  editingId.value = tag.id
  editingName.value = tag.name
}

async function saveEdit() {
  if (!editingName.value.trim() || !editingId.value) return
  await tags.updateTag(editingId.value, { name: editingName.value })
  editingId.value = null
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-4 py-3 border-b border-border">
      <h2 class="text-lg font-semibold text-text-primary">Tags</h2>
      <button
        class="p-1.5 rounded hover:bg-surface-hover text-text-secondary hover:text-accent cursor-pointer transition-colors"
        @click="showCreate = true"
      >
        <Plus :size="18" />
      </button>
    </div>

    <!-- Create tag form -->
    <div v-if="showCreate" class="px-4 py-3 border-b border-border bg-surface">
      <input
        v-model="newTagName"
        class="w-full bg-sidebar border border-border rounded px-2 py-1.5 text-sm text-text-primary mb-2"
        placeholder="Tag name"
        @keyup.enter="createTag"
      />
      <div class="flex gap-2">
        <button
          class="px-3 py-1 rounded bg-accent text-white text-xs cursor-pointer hover:bg-accent-hover transition-colors"
          @click="createTag"
        >
          Add
        </button>
        <button
          class="px-3 py-1 rounded text-xs text-text-secondary hover:text-text-primary cursor-pointer"
          @click="showCreate = false"
        >
          Cancel
        </button>
      </div>
    </div>

    <!-- Tag tree -->
    <div class="flex-1 overflow-y-auto p-2">
      <div v-for="tag in tags.tags" :key="tag.id" class="mb-1">
        <div
          class="flex items-center gap-2 px-3 py-2 rounded hover:bg-surface-hover cursor-pointer group transition-colors"
        >
          <button
            v-if="tag.children.length"
            class="p-0.5 text-text-muted"
            @click.stop="toggle(tag.id)"
          >
            <ChevronRight v-if="!expanded.has(tag.id)" :size="14" />
            <ChevronDown v-else :size="14" />
          </button>
          <span v-else class="w-4" />

          <!-- Inline edit -->
          <input
            v-if="editingId === tag.id"
            v-model="editingName"
            class="flex-1 bg-sidebar border border-border rounded px-2 py-0.5 text-sm text-text-primary"
            @keyup.enter="saveEdit"
            @blur="saveEdit"
          />
          <span v-else class="flex-1 text-sm text-text-primary">
            {{ tag.name }}
            <span class="text-text-muted text-xs ml-1">({{ tag.entry_count }})</span>
          </span>

          <div class="hidden group-hover:flex items-center gap-1">
            <button class="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary" @click.stop="startEdit(tag)">
              <Pencil :size="12" />
            </button>
            <button class="p-1 rounded hover:bg-surface text-text-muted hover:text-danger" @click.stop="deleteTag(tag.id)">
              <Trash2 :size="12" />
            </button>
          </div>
        </div>

        <!-- Children -->
        <div v-if="tag.children.length && expanded.has(tag.id)" class="ml-6">
          <div
            v-for="child in tag.children"
            :key="child.id"
            class="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-surface-hover cursor-pointer text-sm text-text-secondary"
          >
            <span>{{ child.name }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
