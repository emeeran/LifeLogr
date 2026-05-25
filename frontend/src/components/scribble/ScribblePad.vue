<script setup lang="ts">
import { ref, computed } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { StickyNote, Trash2, Eye, Edit3, X } from 'lucide-vue-next'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const content = useLocalStorage<string>('diarium-scribble', '')
const showPreview = ref(false)

const charCount = computed(() => content.value.length)

let saveTimer: ReturnType<typeof setTimeout> | null = null

function onInput() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    // Auto-saved via useLocalStorage reactivity
  }, 500)
}

function clear() {
  if (!content.value.trim()) return
  if (!confirm('Clear scribble pad?')) return
  content.value = ''
}

const renderedPreview = computed(() => {
  if (!content.value.trim()) return ''
  const html = marked(content.value) as string
  return DOMPurify.sanitize(html)
})

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div class="h-full flex flex-col bg-surface border-r border-border">
    <!-- Header -->
    <div class="flex items-center justify-between px-3 py-2 border-b border-border">
      <div class="flex items-center gap-1.5 text-xs font-medium text-text-primary">
        <StickyNote :size="14" class="text-accent" />
        Scribble Pad
      </div>
      <div class="flex items-center gap-1">
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer transition-colors"
          :class="!showPreview ? 'bg-accent/20 text-accent' : ''"
          title="Edit"
          @click="showPreview = false"
        >
          <Edit3 :size="12" />
        </button>
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-secondary cursor-pointer transition-colors"
          :class="showPreview ? 'bg-accent/20 text-accent' : ''"
          title="Preview"
          @click="showPreview = true"
        >
          <Eye :size="12" />
        </button>
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-muted hover:text-danger cursor-pointer transition-colors"
          title="Clear"
          @click="clear"
        >
          <Trash2 :size="12" />
        </button>
        <button
          class="p-1 rounded hover:bg-surface-hover text-text-muted cursor-pointer transition-colors"
          @click="emit('close')"
        >
          <X :size="12" />
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto min-h-0">
      <textarea
        v-if="!showPreview"
        v-model="content"
        class="w-full h-full resize-none bg-transparent p-3 text-sm text-text-primary outline-none leading-relaxed placeholder:text-text-muted/50"
        placeholder="Quick notes, ideas, reminders..."
        @input="onInput"
      />
      <div
        v-else
        class="p-3 text-sm text-text-primary leading-relaxed md-body"
        v-html="renderedPreview"
      />
    </div>

    <!-- Footer -->
    <div class="px-3 py-1 border-t border-border text-[10px] text-text-muted">
      {{ charCount }} chars
    </div>
  </div>
</template>
