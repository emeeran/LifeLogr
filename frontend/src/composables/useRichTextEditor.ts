/**
 * useRichTextEditor — the shared editing core for the journal (EntryEditor) and
 * notes (NoteEditor) editors.
 *
 * Both editors are the same model: a <textarea> bound to a markdown string, with
 * cursor-selection caching and wrap/prepend/insert string-manipulation
 * formatting. This composable owns that engine — selection, formatting actions,
 * active-format detection, undo/redo history, find/replace, AI tools, and
 * keyboard shortcuts — so the two editor shells stay thin.
 *
 * The SHELL owns the `body` and `textarea` refs (it creates them, binds the
 * textarea in its template, and passes them in). The core only mutates
 * `body.value`. Autosave stays shell-owned (save targets differ); the core
 * fires `onChange` after any mutation the shell should treat as dirty, and
 * `onSave` on Ctrl+S.
 */
import { nextTick, ref, type Ref } from 'vue'
import { watchThrottled } from '@vueuse/core'
import { useEditorHistory } from './useEditorHistory'
import { useFindReplace } from './useFindReplace'
import { useAiTools } from './useAiTools'

export interface RichTextEditorOptions {
  body: Ref<string>
  textarea: Ref<HTMLTextAreaElement | null>
  /** Fired after any edit mutation (input, formatting, AI, find/replace) so the
   *  shell can mark dirty + autosave. NOT fired on programmatic body loads. */
  onChange?: () => void
  /** Ctrl+S handler (the shell's save). */
  onSave?: () => void
}

export function useRichTextEditor(opts: RichTextEditorOptions) {
  const { body, textarea } = opts
  const onChange = () => opts.onChange?.()
  const onSave = () => opts.onSave?.()

  // ── History + find/replace ──
  const { undoStack, redoStack, pushHistory, doUndo, doRedo, resetHistory } =
    useEditorHistory(body, textarea)
  const {
    showFind,
    findQuery,
    replaceQuery,
    findIndex,
    findCount,
    jumpToMatch,
    replaceOne,
    replaceAll,
  } = useFindReplace(body, textarea, pushHistory)

  // ── Cached selection (preserved when the editor loses focus) ──
  const cachedSelStart = ref(0)
  const cachedSelEnd = ref(0)
  let selCacheTimer: ReturnType<typeof setTimeout> | null = null

  function cacheSelection() {
    const el = textarea.value
    if (el) {
      cachedSelStart.value = el.selectionStart
      cachedSelEnd.value = el.selectionEnd
    }
  }
  function startSelCache() {
    // Cache on blur with a short delay so click handlers in drawers/menus can
    // still read the selection.
    selCacheTimer = setTimeout(cacheSelection, 0)
  }
  function clearSelCache() {
    if (selCacheTimer) {
      clearTimeout(selCacheTimer)
      selCacheTimer = null
    }
    cacheSelection() // cache immediately on focus too
  }

  // ── Selection access ──
  function getSelectionRaw(): string {
    const el = textarea.value
    if (!el) return ''
    const focused = document.activeElement === el
    const start = focused ? el.selectionStart : cachedSelStart.value
    const end = focused ? el.selectionEnd : cachedSelEnd.value
    return body.value.slice(start, end)
  }
  /** Trimmed selection — for AI empty-selection guards and display. */
  function getSelection(): string {
    return getSelectionRaw().trim()
  }
  function applyToSelection(newText: string) {
    const el = textarea.value
    if (!el) return
    const focused = document.activeElement === el
    const start = focused ? el.selectionStart : cachedSelStart.value
    const end = focused ? el.selectionEnd : cachedSelEnd.value
    body.value = body.value.slice(0, start) + newText + body.value.slice(end)
    pushHistory()
    onChange()
    nextTick(() => {
      el.focus()
      el.selectionStart = start
      el.selectionEnd = start + newText.length
    })
  }

  // ── Formatting primitives ──
  function wrap(before: string, after: string, placeholder = '') {
    const el = textarea.value
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const selected = body.value.slice(start, end) || placeholder
    const replacement = before + selected + after
    body.value = body.value.slice(0, start) + replacement + body.value.slice(end)
    pushHistory()
    onChange()
    nextTick(() => {
      el.focus()
      el.selectionStart = start + before.length
      el.selectionEnd = start + before.length + selected.length
    })
  }
  function prependLine(prefix: string) {
    const el = textarea.value
    if (!el) return
    const start = el.selectionStart
    const lineStart = body.value.lastIndexOf('\n', start - 1) + 1
    body.value = body.value.slice(0, lineStart) + prefix + body.value.slice(lineStart)
    pushHistory()
    onChange()
    nextTick(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = start + prefix.length
    })
  }
  function insertAtCursor(text: string) {
    const el = textarea.value
    if (!el) return
    const start = el.selectionStart
    body.value = body.value.slice(0, start) + text + body.value.slice(el.selectionEnd)
    pushHistory()
    onChange()
    nextTick(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = start + text.length
    })
  }
  /** Markdown table. `insertTable()` → 2×2 template; notes' grid picker passes rows/cols. */
  function insertTable(rows = 2, cols = 2) {
    const header = '| ' + Array(cols).fill('Header').join(' | ') + ' |'
    const sep = '|' + Array(cols).fill('--------').join('|') + '|'
    const row = '| ' + Array(cols).fill('Cell').join('   | ') + '   |'
    insertAtCursor('\n' + header + '\n' + sep + '\n' + (row + '\n').repeat(Math.max(1, rows)))
  }
  /** Horizontal rule sized to the textarea's rendered content width. */
  function makeDivider(char = '*'): string {
    const el = textarea.value
    if (!el) return char.repeat(40)
    const style = window.getComputedStyle(el)
    const ruler = document.createElement('span')
    Object.assign(ruler.style, {
      position: 'absolute',
      visibility: 'hidden',
      whiteSpace: 'pre',
      fontFamily: style.fontFamily,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
    })
    const SAMPLE = 40
    ruler.textContent = char.repeat(SAMPLE)
    document.body.appendChild(ruler)
    const unit = ruler.getBoundingClientRect().width / SAMPLE || parseFloat(style.fontSize) || 8
    ruler.remove()
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
    const usable = el.clientWidth - padding
    const count = Math.max(8, Math.floor((usable - 1) / unit))
    return char.repeat(count)
  }
  /** Notes-only: wrap the selection in a font-family span (HTML, rendered in preview). */
  function wrapFont(font: string) {
    wrap(`<span style="font-family:${font}">`, '</span>', 'font')
  }
  /** Notes-only: wrap the selection in a font-size span. */
  function wrapSize(size: number) {
    wrap(`<span style="font-size:${size}px">`, '</span>', 'text')
  }

  // ── Action registry (toolbar queries by id; superset of both editors) ──
  const actions: Record<string, () => void> = {
    bold: () => wrap('**', '**', 'bold text'),
    italic: () => wrap('*', '*', 'italic text'),
    strikethrough: () => wrap('~~', '~~', 'strikethrough'),
    code: () => wrap('`', '`', 'code'),
    codeBlock: () => wrap('\n```\n', '\n```\n', 'code block'),
    h1: () => prependLine('# '),
    h2: () => prependLine('## '),
    h3: () => prependLine('### '),
    ul: () => prependLine('- '),
    ol: () => prependLine('1. '),
    checklist: () => prependLine('- [ ] '),
    checkbox: () => prependLine('- [ ] '), // alias (older toolbars emit 'checkbox')
    quote: () => prependLine('> '),
    link: () => wrap('[', '](url)', 'link text'),
    image: () => wrap('![', '](url)', 'alt text'),
    hr: () => insertAtCursor('\n\n' + makeDivider() + '\n\n'),
    table: () => insertTable(),
    highlight: () => wrap('<mark>', '</mark>', 'highlighted text'),
    alignLeft: () => wrap('<div style="text-align: left">\n', '\n</div>', 'left aligned text'),
    alignCenter: () => wrap('<div style="text-align: center">\n', '\n</div>', 'centered text'),
    alignRight: () => wrap('<div style="text-align: right">\n', '\n</div>', 'right aligned text'),
    alignJustify: () =>
      wrap('<div style="text-align: justify">\n', '\n</div>', 'justified text'),
    undo: doUndo,
    redo: doRedo,
  }

  // ── Active-format detection (throttled) ──
  const activeFormats = ref(new Set<string>())
  function computeFormats() {
    const el = textarea.value
    if (!el) {
      activeFormats.value = new Set<string>()
      return
    }
    const pos = el.selectionStart
    const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
    const currentLine = body.value.slice(lineStart, pos)
    const s = new Set<string>()
    if (currentLine.startsWith('# ')) s.add('h1')
    if (currentLine.startsWith('## ')) s.add('h2')
    if (currentLine.startsWith('### ')) s.add('h3')
    if (
      currentLine.startsWith('- ') ||
      currentLine.startsWith('* ') ||
      currentLine.startsWith('+ ')
    )
      s.add('ul')
    if (/^\d+\.\s/.test(currentLine)) s.add('ol')
    if (currentLine.startsWith('> ')) s.add('quote')
    if (currentLine.startsWith('- [ ] ') || currentLine.startsWith('- [x] ')) s.add('checklist')

    const before = body.value.slice(Math.max(0, pos - 20), pos)
    const after = body.value.slice(pos, pos + 20)
    const full = body.value.slice(Math.max(0, pos - 40), pos + 40)
    if (
      (before.endsWith('**') && after.startsWith('**')) ||
      (before.endsWith('**') && body.value.slice(pos).startsWith('**'))
    )
      s.add('bold')
    if (
      (before.endsWith('*') && !before.endsWith('**') && after.startsWith('*')) ||
      (before.endsWith('*') &&
        !before.endsWith('**') &&
        body.value.slice(pos).startsWith('*'))
    )
      s.add('italic')
    if (full.includes('<mark>') && full.includes('</mark>')) s.add('highlight')
    if (full.includes('text-align: left')) s.add('alignLeft')
    if (full.includes('text-align: center')) s.add('alignCenter')
    if (full.includes('text-align: right')) s.add('alignRight')
    if (full.includes('text-align: justify')) s.add('alignJustify')
    activeFormats.value = s
  }
  watchThrottled(body, computeFormats, { throttle: 200, immediate: true })

  // ── Keyboard: auto-indent + tab (textarea @keydown) ──
  function onTextareaKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      const el = textarea.value
      if (!el) return
      const pos = el.selectionStart
      const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
      const currentLine = body.value.slice(lineStart, pos)
      const listMatch = currentLine.match(/^(\s*)([-*+]|\d+\.)\s/)
      const checkboxMatch = currentLine.match(/^(\s*)- \[[ x]\]\s/)
      if (listMatch || checkboxMatch) {
        e.preventDefault()
        const prefix = checkboxMatch ? checkboxMatch[1] + '- [ ] ' : listMatch![0]
        if (
          currentLine.trim() === listMatch?.[0]?.trim() ||
          currentLine.trim() === checkboxMatch?.[0]?.trim()
        ) {
          body.value = body.value.slice(0, lineStart) + body.value.slice(pos)
          nextTick(() => {
            el.selectionStart = el.selectionEnd = lineStart
          })
          return
        }
        let newPrefix = prefix
        const numMatch = prefix.match(/^(\s*)(\d+)\.\s/)
        if (numMatch) newPrefix = numMatch[1] + (parseInt(numMatch[2]) + 1) + '. '
        body.value = body.value.slice(0, pos) + '\n' + newPrefix + body.value.slice(pos)
        pushHistory()
        onChange()
        nextTick(() => {
          el.selectionStart = el.selectionEnd = pos + 1 + newPrefix.length
        })
        return
      }
    }
    if (e.key === 'Tab') {
      e.preventDefault()
      const el = textarea.value!
      const pos = el.selectionStart
      if (e.shiftKey) {
        const lineStart = body.value.lastIndexOf('\n', pos - 1) + 1
        const lineContent = body.value.slice(lineStart)
        if (lineContent.startsWith('  ')) {
          body.value = body.value.slice(0, lineStart) + lineContent.slice(2)
          nextTick(() => {
            el.selectionStart = el.selectionEnd = Math.max(lineStart, pos - 2)
          })
        }
      } else {
        insertAtCursor('  ')
      }
    }
  }

  // ── Keyboard: shortcuts (textarea @keydown.capture) ──
  function onShortcutKeydown(e: KeyboardEvent) {
    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key === 'z' && !e.shiftKey) {
      e.preventDefault()
      doUndo()
      return
    }
    if (mod && (e.key === 'y' || (e.key === 'z' && e.shiftKey) || e.key === 'Z')) {
      e.preventDefault()
      doRedo()
      return
    }
    if (mod && e.key === 's') {
      e.preventDefault()
      onSave()
      return
    }
    if (mod && e.key === 'f') {
      e.preventDefault()
      showFind.value = true
      return
    }
    if (e.key === 'Escape' && showFind.value) {
      showFind.value = false
      return
    }
    if (e.key === 'Enter' && showFind.value && findQuery.value) {
      e.preventDefault()
      jumpToMatch(e.shiftKey ? -1 : 1)
      return
    }
    if (!mod) return
    const handlers: Record<string, () => void> = {
      b: actions.bold,
      i: actions.italic,
      k: actions.code,
      u: actions.strikethrough,
    }
    if (mod && e.altKey && e.key.toLowerCase() === 'h') {
      e.preventDefault()
      actions.hr()
      return
    }
    const handler = handlers[e.key.toLowerCase()]
    if (handler) {
      e.preventDefault()
      handler()
    }
  }

  // ── @input handler ──
  function onInput() {
    pushHistory()
    onChange()
  }

  // ── AI tools (selection-based context menu + drawer) ──
  const ai = useAiTools(
    body,
    getSelection,
    applyToSelection,
    cachedSelStart,
    cachedSelEnd,
    textarea,
    pushHistory,
    onChange,
  )

  return {
    // selection
    cachedSelStart,
    cachedSelEnd,
    cacheSelection,
    startSelCache,
    clearSelCache,
    getSelection,
    getSelectionRaw,
    applyToSelection,
    // formatting
    wrap,
    prependLine,
    insertAtCursor,
    insertTable,
    makeDivider,
    wrapFont,
    wrapSize,
    actions,
    activeFormats,
    computeFormats,
    // history
    undoStack,
    redoStack,
    pushHistory,
    doUndo,
    doRedo,
    resetHistory,
    // find/replace
    showFind,
    findQuery,
    replaceQuery,
    findIndex,
    findCount,
    jumpToMatch,
    replaceOne,
    replaceAll,
    // keyboard + input
    onTextareaKeydown,
    onShortcutKeydown,
    onInput,
    // ai
    ...ai,
  }
}
