<script setup lang="ts">
import { ref } from 'vue'
import { useUiStore } from '../../stores/ui'

const ui = useUiStore()
const dragging = ref(false)

function onMousedown(e: MouseEvent) {
  e.preventDefault()
  dragging.value = true
  const startX = e.clientX
  const startWidth = ui.rightPanelWidth

  function onMousemove(ev: MouseEvent) {
    // Dragging splitter left = panel gets wider (distance moved right to left)
    const delta = startX - ev.clientX
    ui.setRightPanelWidth(startWidth + delta)
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
