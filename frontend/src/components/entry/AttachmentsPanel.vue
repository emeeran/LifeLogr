<script setup lang="ts">
import { Trash2, Image, Film, Music, FileText, Sparkles } from 'lucide-vue-next'
import { mediaApi } from '../../api/media'
import { formatFileSize } from '../../composables/useFormat'
import type { MediaResponse } from '../../types'

defineProps<{
  attachments: MediaResponse[]
}>()

const emit = defineEmits<{
  add: []
  remove: [id: number]
  view: [index: number]
  extractText: [id: number]
}>()

function mediaIcon(type: string) {
  if (type === 'image' || type.startsWith('image/')) return Image
  if (type === 'video' || type.startsWith('video/')) return Film
  if (type === 'audio' || type.startsWith('audio/')) return Music
  return FileText
}
</script>

<template>
  <div class="p-3">
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs font-medium text-text-secondary">Attachments ({{ attachments.length }})</span>
      <button class="text-xs text-accent hover:text-accent-hover cursor-pointer" @click="emit('add')">+ Add files</button>
    </div>
    <div v-if="!attachments.length" class="text-xs text-text-muted text-center py-3">
      No attachments yet. Click "Add files" to upload.
    </div>
    <div v-else class="space-y-1.5">
      <div
        v-for="(m, idx) in attachments"
        :key="m.id"
        class="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-hover cursor-pointer hover:bg-surface-hover/80"
        @click="emit('view', idx)"
      >
        <img v-if="m.media_type === 'image' || m.media_type.startsWith('image/')" :src="mediaApi.fileUrl(m.id)" class="w-8 h-8 rounded object-cover shrink-0" />
        <component v-else :is="mediaIcon(m.media_type)" :size="16" class="text-accent shrink-0" />
        <span class="text-xs text-text-primary truncate flex-1">{{ m.filename }}</span>
        <span class="text-[10px] text-text-muted shrink-0">{{ formatFileSize(m.file_size) }}</span>
        <button
          v-if="m.media_type === 'image' || m.media_type.startsWith('image/')"
          class="p-0.5 text-text-muted hover:text-accent cursor-pointer"
          @click.stop="emit('extractText', m.id)"
          title="Extract text (OCR)"
        >
          <Sparkles :size="12" />
        </button>
        <button class="p-0.5 text-text-muted hover:text-red-400 cursor-pointer" @click.stop="emit('remove', m.id)" title="Remove">
          <Trash2 :size="12" />
        </button>
      </div>
    </div>
  </div>
</template>
