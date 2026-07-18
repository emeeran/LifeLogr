<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  icon?: Component
  title: string
  active?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{ click: [] }>()
</script>

<template>
  <button
    class="p-1 rounded cursor-pointer transition-colors"
    :class="active ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
    :disabled="disabled"
    :title="title"
    @click="emit('click')"
  >
    <component v-if="icon" :is="icon" :size="13" />
    <slot />
  </button>
</template>
