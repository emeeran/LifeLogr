<script setup lang="ts">
/**
 * StateView — shared empty / loading / error state component.
 *
 * Replaces the ad-hoc per-view implementations with one consistent primitive.
 * Usage:
 *   <StateView variant="loading" message="Loading entries..." />
 *   <StateView variant="empty" message="No entries yet" :icon="BookOpen" />
 *   <StateView variant="error" message="Failed to load" @retry="load" />
 */
import type { Component } from 'vue'
import { Loader, Inbox, AlertTriangle } from 'lucide-vue-next'

withDefaults(defineProps<{
  variant: 'loading' | 'empty' | 'error'
  message?: string
  hint?: string
  icon?: Component
}>(), {
  message: '',
  hint: '',
})

defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 px-4 text-center">
    <component
      :is="icon ?? (variant === 'loading' ? Loader : variant === 'empty' ? Inbox : AlertTriangle)"
      :size="28"
      class="mb-2 text-text-muted"
      :class="{ 'animate-spin': variant === 'loading' }"
      aria-hidden="true"
    />
    <p class="text-[13px] font-medium text-text-secondary">
      {{ message || (variant === 'loading' ? 'Loading…' : variant === 'empty' ? 'Nothing here yet.' : 'Something went wrong.') }}
    </p>
    <p v-if="hint" class="text-[11px] text-text-muted mt-1 max-w-xs">{{ hint }}</p>
    <button
      v-if="variant === 'error'"
      class="mt-3 px-3 py-1 rounded-md text-[11px] font-medium bg-surface-hover text-text-primary hover:text-accent cursor-pointer transition-colors"
      @click="$emit('retry')"
    >
      Try again
    </button>
  </div>
</template>
