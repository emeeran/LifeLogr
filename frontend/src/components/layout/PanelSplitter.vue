<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Current column width in pixels. */
    modelValue: number
    /** Minimum column width. */
    min?: number
    /** Maximum column width. */
    max?: number
    /** Which edge the handle sits on.
     *  'left'  — column is on the left of the row, drag right to widen it.
     *  'right' — column is on the right of the row, drag left to widen it. */
    side?: 'left' | 'right'
  }>(),
  { min: 200, max: 720, side: 'left' },
)
const emit = defineEmits<{ 'update:modelValue': [number] }>()
const dragging = ref(false)

function onMousedown(e: MouseEvent) {
  e.preventDefault()
  dragging.value = true
  const startX = e.clientX
  const startWidth = props.modelValue

  function onMousemove(ev: MouseEvent) {
    const delta = ev.clientX - startX
    const next = props.side === 'left' ? startWidth + delta : startWidth - delta
    emit('update:modelValue', Math.min(props.max, Math.max(props.min, next)))
  }
  function onMouseup() {
    dragging.value = false
    document.removeEventListener('mousemove', onMousemove)
    document.removeEventListener('mouseup', onMouseup)
  }

  document.addEventListener('mousemove', onMousemove)
  document.addEventListener('mouseup', onMouseup)
}
</script>

<template>
  <div
    class="w-1.5 shrink-0 cursor-col-resize transition-colors relative group"
    :class="dragging ? 'bg-accent' : 'bg-border hover:bg-accent/60'"
    @mousedown="onMousedown"
  >
    <!-- Wider invisible hit area for easier grabbing -->
    <div class="absolute inset-y-0 -left-1 -right-1" />
  </div>
</template>
