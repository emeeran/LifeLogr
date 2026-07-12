<script setup lang="ts">
import { onMounted } from 'vue'
import { useUiStore } from '../../stores/ui'
import { Search as SearchIcon } from 'lucide-vue-next'

const ui = useUiStore()

onMounted(() => ui.openSearchPalette())
</script>

<template>
  <div class="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
    <SearchIcon :size="32" class="opacity-40" />
    <p class="text-xs">Press <kbd class="bg-surface-hover border border-border rounded px-1.5 py-0.5 text-text-secondary">Ctrl+K</kbd> to search</p>
  </div>
</template>
