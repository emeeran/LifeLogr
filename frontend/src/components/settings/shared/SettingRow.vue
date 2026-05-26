<script setup lang="ts">
import type { Component } from 'vue'
defineProps<{
  icon?: Component
  label: string
  indent?: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-2.5">
    <component v-if="icon" :is="icon" :size="12" class="text-text-muted shrink-0" />
    <span class="text-[12px] text-text-secondary flex-1" :class="{ 'pl-[30px]': indent }">{{ label }}</span>
    <slot />
  </div>
</template>
