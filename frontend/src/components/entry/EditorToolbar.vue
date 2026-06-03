<script setup lang="ts">
import {
  Bold, Italic, Strikethrough, Heading1, Heading2,
  List, ListOrdered, Quote, Code, Link, Image, Minus,
  Undo2, Redo2, Search, Type, AlignLeft, AlignCenter, AlignRight, AlignJustify, Highlighter, Smile,
  Table, CheckSquare, Focus, Layout
} from 'lucide-vue-next'
import { useUiStore } from '../../stores/ui'

defineProps<{
  activeFormats: Set<string>
  undoCount: number
  redoCount: number
  showEmoji: boolean
  showFind: boolean
  focusMode: boolean
  typewriterMode: boolean
  ui: ReturnType<typeof useUiStore>
}>()

const emit = defineEmits<{
  action: [name: string]
  toggleEmoji: []
  toggleFind: []
  toggleFocus: []
  toggleTypewriter: []
}>()

function fire(name: string) { emit('action', name) }
</script>

<template>
  <div class="bg-editor/50">
    <!-- Row 1: Font + inline formatting + undo/redo -->
    <div class="flex items-center gap-0.5 px-1.5 py-0.5">
      <select
        class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
        :value="ui.fontFamily"
        @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)"
      >
        <option value="system-ui">System</option>
        <option value="'Segoe UI', sans-serif">Segoe UI</option>
        <option value="'Inter', sans-serif">Inter</option>
        <option value="'Roboto', sans-serif">Roboto</option>
        <option value="'Lora', serif">Lora</option>
        <option value="'Merriweather', serif">Merriweather</option>
        <option value="'JetBrains Mono', monospace">JetBrains Mono</option>
        <option value="monospace">Monospace</option>
      </select>
      <select
        class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
        :value="ui.fontSize"
        @change="ui.setFontSize(Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="s in [12, 13, 14, 15, 16, 18, 20, 22, 24]" :key="s" :value="s">{{ s }}px</option>
      </select>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
        :disabled="undoCount < 2"
        title="Undo (Ctrl+Z)"
        @click="fire('undo')"
      ><Undo2 :size="13" /></button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
        :disabled="!redoCount"
        title="Redo (Ctrl+Y)"
        @click="fire('redo')"
      ><Redo2 :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('bold') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Bold (Ctrl+B)" @click="fire('bold')"><Bold :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('italic') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Italic (Ctrl+I)" @click="fire('italic')"><Italic :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Strikethrough (Ctrl+U)" @click="fire('strikethrough')"><Strikethrough :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Inline code (Ctrl+K)" @click="fire('code')"><Code :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Code block" @click="fire('codeBlock')"><Type :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Link" @click="fire('link')"><Link :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Image" @click="fire('image')"><Image :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded cursor-pointer transition-colors"
        :class="showEmoji ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
        title="Insert Emoji"
        @click="emit('toggleEmoji')"
      ><Smile :size="13" /></button>
      <button
        class="p-1 rounded cursor-pointer transition-colors"
        :class="focusMode ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
        title="Focus Mode"
        @click="emit('toggleFocus')"
      ><Focus :size="13" /></button>
      <button
        class="p-1 rounded cursor-pointer transition-colors"
        :class="typewriterMode ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'"
        title="Typewriter Mode"
        @click="emit('toggleTypewriter')"
      ><Layout :size="13" /></button>
      <span class="flex-1" />
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        :class="showFind ? 'bg-accent/20 text-accent' : ''"
        title="Find & Replace (Ctrl+F)"
        @click="emit('toggleFind')"
      ><Search :size="13" /></button>
    </div>
    <!-- Row 2: Block formatting + Alignment + Highlighter -->
    <div class="flex items-center gap-0.5 px-1.5 py-0.5">
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('h1') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Heading 1" @click="fire('h1')"><Heading1 :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('h2') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Heading 2" @click="fire('h2')"><Heading2 :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('ul') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Bullet list" @click="fire('ul')"><List :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('ol') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Numbered list" @click="fire('ol')"><ListOrdered :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('quote') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Blockquote" @click="fire('quote')"><Quote :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('alignLeft') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Align left" @click="fire('alignLeft')"><AlignLeft :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('alignCenter') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Align center" @click="fire('alignCenter')"><AlignCenter :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('alignRight') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Align right" @click="fire('alignRight')"><AlignRight :size="13" /></button>
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('alignJustify') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Align justify" @click="fire('alignJustify')"><AlignJustify :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="activeFormats.has('highlight') ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:text-text-primary'"
        title="Highlight" @click="fire('highlight')"><Highlighter :size="13" /></button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Checkbox" @click="fire('checkbox')"><CheckSquare :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Table" @click="fire('table')"><Table :size="13" /></button>
      <button class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Horizontal rule" @click="fire('hr')"><Minus :size="13" /></button>
    </div>
  </div>
</template>
