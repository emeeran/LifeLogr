<script setup lang="ts">
import type { Component } from 'vue'
/**
 * SettingRow — a label (with optional description + icon) on the left, and a
 * control slot on the right. The control area is flex-1 and right-aligned so
 * that:
 *   - fixed controls (toggles, w-44 selects) sit at the row's right edge, and
 *   - growing controls (`flex-1` inputs in forms) fill the remaining space.
 */
defineProps<{
  icon?: Component
  label: string
  description?: string
  indent?: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-2.5">
    <component v-if="icon" :is="icon" :size="13" class="text-text-muted shrink-0 mt-0.5" aria-hidden="true" />
    <div class="w-32 shrink-0 min-w-0" :class="{ 'pl-[31px]': indent }">
      <div class="text-[13px] text-text-secondary leading-tight">{{ label }}</div>
      <p v-if="description" class="text-[10.5px] text-text-muted mt-0.5 leading-snug">{{ description }}</p>
    </div>
    <div class="flex-1 min-w-0 flex items-center justify-end gap-1.5">
      <slot />
    </div>
  </div>
</template>
