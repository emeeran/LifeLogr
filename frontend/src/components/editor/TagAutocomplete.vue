<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  rows: { id: number; name: string; create?: boolean }[]
  activeIndex: number
  coords: { x: number; y: number }
}>()
const emit = defineEmits<{ pick: [name: string] }>()

// Keep the popover on-screen when the caret is near the right edge.
const clampedLeft = computed(() =>
  Math.max(
    8,
    Math.min(
      props.coords.x,
      (typeof window !== 'undefined' ? window.innerWidth : 9999) - 240,
    ),
  ),
)
</script>

<template>
  <div
    class="tag-ac"
    :style="{ left: clampedLeft + 'px', top: coords.y + 'px' }"
  >
    <button
      v-for="(r, i) in rows"
      :key="r.id + ':' + r.name"
      class="tag-ac-item"
      :class="{ active: i === activeIndex, create: r.create }"
      :title="r.create ? `Create tag #${r.name}` : `#${r.name}`"
      @mousedown.prevent="emit('pick', r.name)"
    >
      <span v-if="r.create" class="tag-ac-plus">+</span>
      <span class="truncate">#{{ r.name }}</span>
    </button>
    <div v-if="!rows.length" class="tag-ac-empty">Type a tag name…</div>
  </div>
</template>

<style scoped>
.tag-ac {
  position: fixed;
  z-index: 60;
  width: 220px;
  max-height: 240px;
  overflow-y: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  padding: 4px;
}
.tag-ac-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  width: 100%;
  padding: 0.32rem 0.5rem;
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
}
.tag-ac-item:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}
.tag-ac-item.active {
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  color: var(--color-accent);
}
.tag-ac-item.create {
  color: var(--color-accent);
}
.tag-ac-plus {
  font-weight: 700;
}
.tag-ac-empty {
  padding: 0.4rem 0.5rem;
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
