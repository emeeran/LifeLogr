<script setup lang="ts">
/**
 * SButton — single source of truth for buttons across the settings surface.
 *
 * Replaces the ~4 ad-hoc inline button class strings (primary / ghost /
 * accent-soft / danger-soft / outline) that were duplicated in every tab.
 * Use `variant` + `size`; slot content is the label.
 */
import type { Component } from 'vue'

withDefaults(defineProps<{
  variant?: 'primary' | 'ghost' | 'outline' | 'accent-soft' | 'danger-soft' | 'danger'
  size?: 'sm' | 'xs'
  icon?: Component
  disabled?: boolean
  title?: string
  type?: 'button' | 'submit'
}>(), {
  variant: 'ghost',
  size: 'sm',
  disabled: false,
  type: 'button',
})

defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :title="title"
    :aria-label="title"
    class="sbtn"
    :class="[`sbtn-${variant}`, size === 'xs' ? 'sbtn-xs' : 'sbtn-sm']"
    @click="$emit('click', $event)"
  >
    <component v-if="icon" :is="icon" :size="size === 'xs' ? 11 : 12" aria-hidden="true" />
    <slot />
  </button>
</template>
