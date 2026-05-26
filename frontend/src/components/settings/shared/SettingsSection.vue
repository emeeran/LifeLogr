<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  title: string
  icon?: Component
  description?: string
  resetLabel?: string
  cardClass?: string
}>()

const emit = defineEmits<{
  reset: []
}>()
</script>

<template>
  <section>
    <div class="flex items-start justify-between mb-1.5">
      <div>
        <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1.5">
          <component v-if="icon" :is="icon" :size="12" />
          {{ title }}
        </h3>
        <p v-if="description" class="text-[10px] text-text-muted mt-0.5">{{ description }}</p>
      </div>
      <div class="flex items-center gap-2 shrink-0 pt-0.5">
        <slot name="actions" />
        <button v-if="resetLabel" @click="emit('reset')"
          class="text-[10px] text-text-muted hover:text-accent cursor-pointer transition-colors">
          {{ resetLabel }}
        </button>
      </div>
    </div>
    <div class="bg-surface rounded-md border border-border" :class="cardClass ?? 'p-3 space-y-2'">
      <slot />
    </div>
  </section>
</template>
