<script setup lang="ts">
/**
 * NoteColorPicker — a swatch button + popover for a notebook/note colour label.
 *
 * Emits the persisted hex value (or null for "None") immediately; the owner
 * decides whether that means `store.updateFolder` or `store.updateNote`.
 * Colour is never the only signal: the trigger's tooltip and aria-label name
 * the colour, and the tree rows carry an aria-label too.
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { Check, Palette } from 'lucide-vue-next'
import {
  NOTE_COLORS,
  noteColorLabel,
  noteColorValue,
} from '../../utils/noteColors'

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    /** "notebook" / "note" — used in the accessible name. */
    noun?: string
  }>(),
  { noun: 'item' },
)

const emit = defineEmits<{ 'update:modelValue': [string | null] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const current = computed(() => noteColorValue(props.modelValue))
const label = computed(() => noteColorLabel(props.modelValue))

function toggle() {
  open.value = !open.value
}

function choose(value: string | null) {
  emit('update:modelValue', value)
  open.value = false
}

function onDocumentPointer(e: Event) {
  if (!open.value) return
  if (root.value && e.target instanceof Node && root.value.contains(e.target)) {
    return
  }
  open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) {
    e.stopPropagation()
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
      class="color-trigger"
      :title="`Colour: ${label ?? 'None'}`"
      :aria-label="`${noun} colour: ${label ?? 'None'}`"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <span
        v-if="current"
        class="color-dot"
        :style="{ background: current }"
      />
      <Palette v-else :size="12" class="text-text-muted" />
    </button>

    <div
      v-if="open"
      class="color-popover"
      role="menu"
      :aria-label="`${noun} colour`"
      @click.stop
    >
      <button
        v-for="c in NOTE_COLORS"
        :key="c.id"
        type="button"
        role="menuitemradio"
        :aria-checked="current?.toLowerCase() === c.value.toLowerCase()"
        :aria-label="c.label"
        :title="c.label"
        class="swatch"
        :style="{ background: c.value }"
        @click="choose(c.value)"
      >
        <Check
          v-if="current?.toLowerCase() === c.value.toLowerCase()"
          :size="10"
          class="text-white"
        />
      </button>
      <button
        type="button"
        role="menuitem"
        class="none"
        :class="{ active: !current }"
        @click="choose(null)"
      >
        None
      </button>
    </div>
  </div>
</template>

<style scoped>
.color-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.12s;
}
.color-trigger:hover {
  background: var(--color-surface-hover);
}
.color-dot {
  width: 10px;
  height: 10px;
  border-radius: 9999px;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-border) 70%, transparent);
}
.color-popover {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  z-index: 60;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
}
.swatch {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid color-mix(in srgb, #000 18%, transparent);
}
.swatch:hover {
  transform: scale(1.08);
}
.none {
  grid-column: 1 / -1;
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.none:hover,
.none.active {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
</style>
