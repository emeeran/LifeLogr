<script setup lang="ts">
/**
 * FolderMovePicker — a keyboard-accessible "Move to…" control for a notebook.
 *
 * Drag-and-drop is the fast path; this is the equivalent for keyboard and
 * screen-reader users (and the only way to move a notebook without a mouse).
 * Options exclude the folder itself and its descendants, mirroring the
 * cycle guard the drag path applies.
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { Check, FolderInput } from 'lucide-vue-next'
import {
  isDescendant,
  type FolderLink,
} from '../../composables/useNotesTreeDrag'

export interface MoveFolderOption extends FolderLink {
  name: string
}

const props = defineProps<{
  folderId: number
  parentId: number | null
  folders: MoveFolderOption[]
}>()

const emit = defineEmits<{ move: [number | null] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const options = computed(() =>
  props.folders
    .filter((f) => !isDescendant(props.folders, props.folderId, f.id))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name)),
)

function toggle() {
  open.value = !open.value
}

function choose(parentId: number | null) {
  emit('move', parentId)
  open.value = false
}

function onDocumentPointer(event: Event) {
  if (!open.value) return
  if (root.value && event.target instanceof Node && root.value.contains(event.target)) {
    return
  }
  open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.stopPropagation()
    open.value = false
  }
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointer, true)
    document.addEventListener('keydown', onKeydown, true)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointer, true)
    document.removeEventListener('keydown', onKeydown, true)
  }
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointer, true)
  document.removeEventListener('keydown', onKeydown, true)
})
</script>

<template>
  <div ref="root" class="relative shrink-0">
    <button
      type="button"
      class="move-trigger"
      title="Move notebook to…"
      aria-label="Move notebook to another notebook"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <FolderInput :size="11" />
    </button>

    <div
      v-if="open"
      class="move-popover"
      role="menu"
      aria-label="Move notebook to"
      @click.stop
    >
      <span class="move-heading">Move to</span>
      <button
        type="button"
        role="menuitemradio"
        :aria-checked="parentId === null"
        class="move-option"
        @click="choose(null)"
      >
        <Check v-if="parentId === null" :size="10" />
        <span class="truncate">Top level</span>
      </button>
      <button
        v-for="option in options"
        :key="option.id"
        type="button"
        role="menuitemradio"
        :aria-checked="parentId === option.id"
        class="move-option"
        @click="choose(option.id)"
      >
        <Check v-if="parentId === option.id" :size="10" />
        <span class="truncate">{{ option.name }}</span>
      </button>
      <p v-if="!options.length" class="move-empty">No other notebooks yet.</p>
    </div>
  </div>
</template>

<style scoped>
.move-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  color: var(--color-text-muted);
  cursor: pointer;
}
.move-trigger:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.move-popover {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  z-index: 60;
  min-width: 150px;
  max-height: 240px;
  overflow-y: auto;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
}
.move-heading {
  display: block;
  padding: 2px 6px 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.move-option {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 11px;
  text-align: left;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.move-option:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.move-empty {
  padding: 4px 6px;
  font-size: 10px;
  color: var(--color-text-muted);
}
</style>
