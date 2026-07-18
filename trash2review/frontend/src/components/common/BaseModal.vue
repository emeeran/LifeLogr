<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { X } from 'lucide-vue-next'
import type { Component } from 'vue'

const props = defineProps<{
  modelValue: boolean
  title: string
  icon?: Component
  maxWidth?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function close() {
  emit('update:modelValue', false)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Transition name="modal">
    <div v-if="modelValue" class="fixed inset-0 z-[200] flex items-center justify-center bg-black/40" @click.self="close">
      <div class="bg-surface border border-border rounded-lg shadow-xl flex flex-col overflow-hidden"
        :style="{ width: maxWidth || '480px', maxHeight: '90vh' }">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <span class="text-sm font-semibold text-text-primary flex items-center gap-2">
            <component v-if="icon" :is="icon" :size="16" class="text-accent" />
            {{ title }}
          </span>
          <button class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer" @click="close">
            <X :size="14" />
          </button>
        </div>

        <!-- Body slot -->
        <div class="flex-1 overflow-y-auto p-4">
          <slot />
        </div>

        <!-- Footer slot -->
        <div v-if="$slots.footer" class="flex justify-end gap-2 px-4 py-3 border-t border-border shrink-0">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
