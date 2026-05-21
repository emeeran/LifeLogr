<script setup lang="ts">
import { Tag } from 'lucide-vue-next'
import type { TagBrief } from '../../types'

defineProps<{ tag: TagBrief }>()
</script>

<template>
  <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-tag-chip text-white text-xs font-medium">
    <Tag :size="10" />
    {{ tag.name }}
  </span>
</template>
