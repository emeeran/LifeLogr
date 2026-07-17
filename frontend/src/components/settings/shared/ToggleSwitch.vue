<script setup lang="ts">
defineProps<{
  modelValue: boolean
  disabled?: boolean
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out disabled:opacity-40 disabled:cursor-not-allowed"
    :class="modelValue ? 'bg-accent' : 'bg-border'"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      aria-hidden="true"
      class="pointer-events-none absolute top-[2px] left-[2px] inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out"
      :class="modelValue ? 'translate-x-4' : 'translate-x-0'"
    />
  </button>
</template>
