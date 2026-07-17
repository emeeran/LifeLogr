<script setup lang="ts">
withDefaults(defineProps<{ lines?: number }>(), { lines: 3 })
</script>

<template>
  <div class="space-y-2">
    <div v-for="i in lines" :key="i"
      class="h-3 rounded-md bg-border/50 animate-pulse"
      :class="i === lines ? 'w-3/5' : 'w-full'" />
  </div>
</template>
