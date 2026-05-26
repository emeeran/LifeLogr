<script setup lang="ts">
import type { Component } from 'vue'
import { ref } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  title: string
  icon?: Component
  description?: string
  defaultOpen?: boolean
}>(), {
  defaultOpen: false
})

const isOpen = ref(props.defaultOpen)
</script>

<template>
  <section>
    <button
      @click="isOpen = !isOpen"
      class="w-full flex items-center gap-1.5 text-[11px] font-medium text-text-muted uppercase tracking-wide cursor-pointer select-none hover:text-text-secondary transition-colors rounded-sm"
      :aria-expanded="isOpen"
    >
      <component v-if="icon" :is="icon" :size="12" />
      {{ title }}
      <ChevronDown :size="12" class="ml-auto text-text-muted transition-transform duration-200" :class="isOpen ? 'rotate-180' : ''" />
    </button>
    <div class="grid transition-all duration-200 ease-in-out"
      :class="isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
      <div class="overflow-hidden">
        <div class="pt-1.5">
          <div class="bg-surface rounded-md p-3 border border-border">
            <slot />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
