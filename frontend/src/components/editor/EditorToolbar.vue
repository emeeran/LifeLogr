<script setup lang="ts">
/**
 * EditorToolbar — the shared formatting toolbar for the journal and notes
 * editors. Presentational: props in, `@action(name)` out (the shell maps names
 * to `core.actions[name]`). The `mode` prop controls which tool groups are
 * visible so each editor shows only its relevant tools.
 */
import {
  Bold,
  Italic,
  Strikethrough,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Code,
  Link,
  Image as ImageIcon,
  ImagePlus,
  Video,
  Music,
  Minus,
  Undo2,
  Redo2,
  Search,
  Type,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  Highlighter,
  Smile,
  Table,
  CheckSquare,
  Focus,
  Layout,
  Scissors,
  Globe,
} from 'lucide-vue-next'
import { useUiStore } from '../../stores/ui'

defineProps<{
  mode: 'journal' | 'notes'
  activeFormats: Set<string>
  undoCount: number
  redoCount: number
  showEmoji: boolean
  showFind: boolean
  // journal-only toggles
  focusMode?: boolean
  typewriterMode?: boolean
  ui: ReturnType<typeof useUiStore>
  // notes-only: clipping tools (screen snip / web clip) are desktop-only.
  isDesktop?: boolean
}>()

const emit = defineEmits<{
  action: [name: string]
  quickEmoji: [emoji: string]
  toggleEmoji: []
  toggleFind: []
  toggleFocus: []
  toggleTypewriter: []
}>()

function fire(name: string) {
  emit('action', name)
}

// Shared font/size lists. Both editors set the display font/size of the whole
// editor via the ui store — nothing is written into the note/entry body.
const FONT_FAMILIES: { label: string; value: string }[] = [
  { label: 'System', value: 'system-ui' },
  { label: 'Sans', value: "'Segoe UI', sans-serif" },
  { label: 'Serif', value: 'Lora, serif' },
  { label: 'Mono', value: "'JetBrains Mono', monospace" },
]

// Curated journaling markers — one-click insert into the editor body (journal only).
const journalEmojis = ['📝', '💭', '✨', '🙏', '🩺', '💡']
</script>

<template>
  <div class="bg-editor/50">
    <!-- Row 1: Font + inline formatting + undo/redo -->
    <div
      role="toolbar"
      aria-label="Text formatting"
      class="flex items-center gap-0.5 px-1.5 py-0.5 flex-wrap"
    >
      <!-- Display font (whole editor) via the ui store -->
      <select
        class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
        :value="ui.fontFamily"
        @change="ui.setFontFamily(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="f in FONT_FAMILIES" :key="f.value" :value="f.value">
          {{ f.label }}
        </option>
        <option value="'Merriweather', serif">Merriweather</option>
        <option value="'Inter', sans-serif">Inter</option>
        <option value="'Roboto', sans-serif">Roboto</option>
        <option value="monospace">Monospace</option>
      </select>
      <select
        class="bg-surface border border-border rounded px-1 py-0.5 text-[11px] text-text-primary outline-none cursor-pointer hover:border-accent transition-colors"
        :value="ui.fontSize"
        @change="
          ui.setFontSize(Number(($event.target as HTMLSelectElement).value))
        "
      >
        <option
          v-for="s in [12, 13, 14, 15, 16, 18, 20, 22, 24]"
          :key="s"
          :value="s"
        >
          {{ s }}px
        </option>
      </select>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
        :disabled="undoCount < 2"
        title="Undo (Ctrl+Z)"
        aria-label="Undo (Ctrl+Z)"
        @click="fire('undo')"
      >
        <Undo2 :size="13" />
      </button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors disabled:opacity-30"
        :disabled="!redoCount"
        title="Redo (Ctrl+Y)"
        aria-label="Redo (Ctrl+Y)"
        @click="fire('redo')"
      >
        <Redo2 :size="13" />
      </button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('bold')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Bold (Ctrl+B)"
        aria-label="Bold (Ctrl+B)"
        @click="fire('bold')"
      >
        <Bold :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('italic')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Italic (Ctrl+I)"
        aria-label="Italic (Ctrl+I)"
        @click="fire('italic')"
      >
        <Italic :size="13" />
      </button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Strikethrough (Ctrl+U)"
        aria-label="Strikethrough (Ctrl+U)"
        @click="fire('strikethrough')"
      >
        <Strikethrough :size="13" />
      </button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Inline code (Ctrl+K)"
        aria-label="Inline code (Ctrl+K)"
        @click="fire('code')"
      >
        <Code :size="13" />
      </button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Code block"
        aria-label="Code block"
        @click="fire('codeBlock')"
      >
        <Type :size="13" />
      </button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Link"
        aria-label="Link"
        @click="fire('link')"
      >
        <Link :size="13" />
      </button>
      <button
        v-if="mode === 'journal'"
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Image (markdown)"
        aria-label="Image (markdown)"
        @click="fire('image')"
      >
        <ImageIcon :size="13" />
      </button>
      <template v-if="mode === 'notes'">
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Embed image"
          aria-label="Embed image"
          @click="fire('embedImage')"
        >
          <ImagePlus :size="13" />
        </button>
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Embed audio"
          aria-label="Embed audio"
          @click="fire('embedAudio')"
        >
          <Music :size="13" />
        </button>
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Embed video"
          aria-label="Embed video"
          @click="fire('embedVideo')"
        >
          <Video :size="13" />
        </button>
        <button
          v-if="isDesktop"
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Snip screen region (Ctrl+Shift+S) → OCR"
          aria-label="Snip screen region (Ctrl+Shift+S) → OCR"
          @click="fire('clipSnip')"
        >
          <Scissors :size="13" />
        </button>
        <button
          class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
          title="Clip web page"
          aria-label="Clip web page"
          @click="fire('clipWeb')"
        >
          <Globe :size="13" />
        </button>
      </template>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded cursor-pointer transition-colors"
        :class="
          showEmoji
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
        "
        title="Insert Emoji"
        aria-label="Insert Emoji"
        @click="emit('toggleEmoji')"
      >
        <Smile :size="13" />
      </button>
      <template v-if="mode === 'journal'">
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="
            focusMode
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
          "
          title="Focus Mode"
          aria-label="Focus Mode"
          @click="emit('toggleFocus')"
        >
          <Focus :size="13" />
        </button>
        <button
          class="p-1 rounded cursor-pointer transition-colors"
          :class="
            typewriterMode
              ? 'bg-accent/20 text-accent'
              : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
          "
          title="Typewriter Mode"
          aria-label="Typewriter Mode"
          @click="emit('toggleTypewriter')"
        >
          <Layout :size="13" />
        </button>
      </template>
      <span class="flex-1" />
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        :class="showFind ? 'bg-accent/20 text-accent' : ''"
        title="Find & Replace (Ctrl+F)"
        aria-label="Find & Replace (Ctrl+F)"
        @click="emit('toggleFind')"
      >
        <Search :size="13" />
      </button>
    </div>
    <!-- Row 2: Block formatting + Alignment + insert tools -->
    <div
      role="toolbar"
      aria-label="Block formatting and alignment"
      class="flex items-center gap-0.5 px-1.5 py-0.5 flex-wrap"
    >
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('h1')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Heading 1"
        aria-label="Heading 1"
        @click="fire('h1')"
      >
        <Heading1 :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('h2')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Heading 2"
        aria-label="Heading 2"
        @click="fire('h2')"
      >
        <Heading2 :size="13" />
      </button>
      <button
        v-if="mode === 'notes'"
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('h3')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Heading 3"
        aria-label="Heading 3"
        @click="fire('h3')"
      >
        <Heading3 :size="13" />
      </button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('ul')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Bullet list"
        aria-label="Bullet list"
        @click="fire('ul')"
      >
        <List :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('ol')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Numbered list"
        aria-label="Numbered list"
        @click="fire('ol')"
      >
        <ListOrdered :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('checklist')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Checklist"
        aria-label="Checklist"
        @click="fire('checklist')"
      >
        <CheckSquare :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('quote')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Blockquote"
        aria-label="Blockquote"
        @click="fire('quote')"
      >
        <Quote :size="13" />
      </button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('alignLeft')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Align left"
        aria-label="Align left"
        @click="fire('alignLeft')"
      >
        <AlignLeft :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('alignCenter')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Align center"
        aria-label="Align center"
        @click="fire('alignCenter')"
      >
        <AlignCenter :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('alignRight')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Align right"
        aria-label="Align right"
        @click="fire('alignRight')"
      >
        <AlignRight :size="13" />
      </button>
      <button
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('alignJustify')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Align justify"
        aria-label="Align justify"
        @click="fire('alignJustify')"
      >
        <AlignJustify :size="13" />
      </button>
      <span class="w-px h-4 bg-border mx-0.5" />
      <button
        v-if="mode === 'journal'"
        class="p-1 rounded hover:bg-surface-hover cursor-pointer transition-colors"
        :class="
          activeFormats.has('highlight')
            ? 'bg-accent/20 text-accent'
            : 'text-text-secondary hover:text-text-primary'
        "
        title="Highlight"
        aria-label="Highlight"
        @click="fire('highlight')"
      >
        <Highlighter :size="13" />
      </button>
      <button
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Table"
        aria-label="Table"
        @click="fire('table')"
      >
        <Table :size="13" />
      </button>
      <button
        v-if="mode === 'journal'"
        class="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover cursor-pointer transition-colors"
        title="Horizontal rule"
        aria-label="Horizontal rule"
        @click="fire('hr')"
      >
        <Minus :size="13" />
      </button>
    </div>
    <!-- Row 3: Journal quick-insert emojis (journal only) -->
    <div
      v-if="mode === 'journal'"
      role="toolbar"
      aria-label="Journal quick inserts"
      class="flex items-center gap-0.5 px-1.5 py-0.5 border-t border-border/50"
    >
      <span
        class="text-[9px] uppercase tracking-wider text-text-muted font-semibold mr-1 select-none"
        >Journal</span
      >
      <button
        v-for="emoji in journalEmojis"
        :key="emoji"
        class="w-6 h-6 flex items-center justify-center text-base hover:bg-surface-hover rounded cursor-pointer transition-colors"
        :title="`Insert ${emoji}`"
        :aria-label="`Insert ${emoji}`"
        @click="emit('quickEmoji', emoji)"
      >
        {{ emoji }}
      </button>
    </div>
  </div>
</template>
