import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'
import { useRichTextEditor } from './useRichTextEditor'

/**
 * Tests for the shared editing core (useRichTextEditor) — the engine both the
 * journal EntryEditor and NoteEditor are thin shells around.
 *
 * The composable is textarea-based (not contenteditable): the SHELL owns the
 * `body` ref and the `textarea` ref, so each test wires a real happy-dom
 * <textarea> into the document and drives selection with selectionStart/End —
 * exactly what a browser gives the composable.
 */

function setup(initial = '') {
  const body = ref(initial)
  const el = document.createElement('textarea')
  el.value = initial
  document.body.appendChild(el)
  const textarea = ref<HTMLTextAreaElement | null>(el)
  const onChange = vi.fn()
  const onSave = vi.fn()
  const core = useRichTextEditor({ body, textarea, onChange, onSave })
  return { body, el, textarea, core, onChange, onSave }
}

function key(key: string, init: KeyboardEventInit = {}): KeyboardEvent {
  return new KeyboardEvent('keydown', { key, cancelable: true, ...init })
}

/** Select [start, end) in the fixture textarea, the way the shell's @input path does. */
function select(
  el: HTMLTextAreaElement,
  start: number,
  end = start,
) {
  el.focus()
  el.selectionStart = start
  el.selectionEnd = end
}

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('undo / redo history', () => {
  it('pushes a snapshot per edit and undo restores the previous body', () => {
    const { body, core } = setup('first')
    core.pushHistory()

    body.value = 'first edit'
    core.pushHistory()
    expect(core.undoStack.value.map((e) => e.content)).toEqual([
      'first',
      'first edit',
    ])

    core.doUndo()
    expect(body.value).toBe('first')
    expect(core.redoStack.value.map((e) => e.content)).toEqual(['first edit'])
  })

  it('redo re-applies the undone snapshot and clears on a new edit', () => {
    const { body, core } = setup('a')
    core.pushHistory()
    body.value = 'ab'
    core.pushHistory()
    core.doUndo()
    expect(body.value).toBe('a')

    core.doRedo()
    expect(body.value).toBe('ab')
    expect(core.redoStack.value).toHaveLength(0)

    // A fresh edit invalidates the redo branch.
    body.value = 'abc'
    core.pushHistory()
    expect(core.redoStack.value).toHaveLength(0)
  })

  it('undoing past the first snapshot restores the empty base state', () => {
    const { body, core } = setup('only')
    core.pushHistory()
    core.doUndo()
    expect(body.value).toBe('')
    // Nothing left to undo — a second undo is a safe no-op.
    core.doUndo()
    expect(body.value).toBe('')
  })

  it('undo / redo restore the snapshot cursor into the textarea', async () => {
    const { body, el, core } = setup('hello world')
    core.pushHistory()
    select(el, 11)
    body.value = 'hello brave world'
    core.pushHistory()
    expect(el.selectionStart).toBe(11)

    core.doUndo()
    await nextTick()
    expect(body.value).toBe('hello world')
    expect(el.selectionStart).toBe(11)
    expect(el.selectionEnd).toBe(11)

    core.doRedo()
    await nextTick()
    expect(el.selectionStart).toBe(11)
  })

  it('coalesces rapid edits (<500ms apart) into a single undo step', () => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    const { body, core } = setup('a')
    core.pushHistory() // base snapshot @ t=0

    vi.setSystemTime(100)
    body.value = 'ab'
    core.pushHistory() // stack length is 1 → must NOT coalesce into the base
    expect(core.undoStack.value).toHaveLength(2)

    vi.setSystemTime(200)
    body.value = 'abc'
    core.pushHistory() // within 500ms and depth ≥ 2 → replaces the last entry
    expect(core.undoStack.value).toHaveLength(2)
    expect(core.undoStack.value[1].content).toBe('abc')

    vi.setSystemTime(1200)
    body.value = 'abcd'
    core.pushHistory() // outside the coalesce window → new step
    expect(core.undoStack.value.map((e) => e.content)).toEqual([
      'a',
      'abc',
      'abcd',
    ])
  })

  it('a push with unchanged content is a no-op', () => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    const { body, core } = setup('a')
    core.pushHistory()
    vi.advanceTimersByTime(1000)
    body.value = 'ab'
    core.pushHistory()
    vi.advanceTimersByTime(1000)
    body.value = 'abc'
    core.pushHistory()
    expect(core.undoStack.value).toHaveLength(3)

    core.doUndo()
    expect(body.value).toBe('ab')
    vi.advanceTimersByTime(100)
    core.pushHistory() // identical to the newest snapshot → nothing recorded
    expect(core.undoStack.value.map((e) => e.content)).toEqual(['a', 'ab'])
  })

  it('caps the stack at the 60-entry depth budget', () => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    const { body, core } = setup('')
    for (let i = 0; i < 70; i++) {
      body.value = 'x'.repeat(i + 1)
      core.pushHistory()
      vi.advanceTimersByTime(1000) // break the coalesce window every push
    }
    expect(core.undoStack.value.length).toBeLessThanOrEqual(60)
    expect(core.undoStack.value[core.undoStack.value.length - 1].content).toBe(
      'x'.repeat(70),
    )
  })

  it('resetHistory starts a fresh stack scoped to the new document', () => {
    const { body, core } = setup('old document')
    core.pushHistory()
    body.value = 'old document v2'
    core.pushHistory()

    body.value = 'new document'
    core.resetHistory()
    // Only the base snapshot of the new document remains — undo cannot cross
    // the entity boundary.
    expect(core.undoStack.value).toHaveLength(1)
    expect(core.undoStack.value[0].content).toBe('new document')
    expect(core.redoStack.value).toHaveLength(0)
    core.doUndo()
    expect(body.value).toBe('')
  })
})

describe('selection helpers', () => {
  it('getSelection returns the focused textarea selection', () => {
    const { el, core } = setup('hello world')
    select(el, 6, 11)
    expect(core.getSelection()).toBe('world')
  })

  it('falls back to the cached selection once the textarea loses focus', () => {
    const { el, core } = setup('hello world')
    select(el, 6, 11)
    core.cacheSelection()
    el.blur()
    expect(core.getSelection()).toBe('world')
  })

  it('startSelCache snapshots the selection on the tick after blur', () => {
    vi.useFakeTimers()
    const { el, core } = setup('hello world')
    select(el, 0, 5)
    core.startSelCache()
    vi.advanceTimersByTime(10)
    el.blur()
    expect(core.getSelection()).toBe('hello')

    // clearSelCache caches immediately (no tick needed).
    select(el, 6, 11)
    core.clearSelCache()
    el.blur()
    expect(core.getSelection()).toBe('world')
  })

  it('is empty when there is no textarea bound', () => {
    const body = ref('untouched')
    const core = useRichTextEditor({
      body,
      textarea: ref<HTMLTextAreaElement | null>(null),
    })
    expect(core.getSelection()).toBe('')
  })
})

describe('formatting actions', () => {
  it('bold wraps the selection (or inserts a placeholder)', async () => {
    const { body, el, core, onChange } = setup('hello world')
    select(el, 0, 5)
    core.actions.bold()
    expect(body.value).toBe('**hello** world')
    expect(onChange).toHaveBeenCalled()
    await nextTick()
    // Selection is restored over the wrapped inner text.
    expect(el.selectionStart).toBe(2)
    expect(el.selectionEnd).toBe(7)
  })

  it('italic, strikethrough, code and codeBlock wrap their markers', () => {
    const { body, el, core } = setup('word')
    select(el, 0, 4)
    core.actions.italic()
    expect(body.value).toBe('*word*')

    body.value = 'word'
    select(el, 0, 4)
    core.actions.strikethrough()
    expect(body.value).toBe('~~word~~')

    body.value = 'word'
    select(el, 0, 4)
    core.actions.code()
    expect(body.value).toBe('`word`')

    body.value = 'word'
    select(el, 0, 4)
    core.actions.codeBlock()
    expect(body.value).toBe('\n```\nword\n```\n')
  })

  it('link wraps the selection in a markdown link, image in an embed', () => {
    const { body, el, core } = setup('click here')
    select(el, 0, 10)
    core.actions.link()
    expect(body.value).toBe('[click here](url)')

    body.value = 'cat.png'
    select(el, 0, 7)
    core.actions.image()
    expect(body.value).toBe('![cat.png](url)')
  })

  it('highlight and the align actions wrap in HTML blocks', () => {
    const { body, el, core } = setup('note')
    select(el, 0, 4)
    core.actions.highlight()
    expect(body.value).toBe('<mark>note</mark>')

    body.value = 'note'
    select(el, 0, 4)
    core.actions.alignCenter()
    expect(body.value).toBe(
      '<div style="text-align: center">\nnote\n</div>',
    )
  })

  it('headings, lists, quote and checklist prepend to the current line only', () => {
    const { body, el, core } = setup('line one\nline two')
    select(el, 14) // inside the second line
    core.actions.h1()
    expect(body.value).toBe('line one\n# line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.h2()
    expect(body.value).toBe('line one\n## line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.h3()
    expect(body.value).toBe('line one\n### line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.ul()
    expect(body.value).toBe('line one\n- line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.ol()
    expect(body.value).toBe('line one\n1. line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.quote()
    expect(body.value).toBe('line one\n> line two')

    body.value = 'line one\nline two'
    select(el, 14)
    core.actions.checklist()
    expect(body.value).toBe('line one\n- [ ] line two')
  })

  it('insertTable inserts the 2x2 template at the cursor', () => {
    const { body, el, core } = setup('')
    select(el, 0)
    core.actions.table()
    expect(body.value).toBe(
      '\n| Header | Header |\n|--------|--------|\n| Cell   | Cell   |\n| Cell   | Cell   |\n',
    )
  })

  it('hr inserts blank-line-wrapped rule (divider length is layout-dependent)', () => {
    const { body, el, core } = setup('')
    select(el, 0)
    core.actions.hr()
    // happy-dom has no layout, so makeDivider() renders an empty ruler; the
    // action still inserts the surrounding blank lines. Browsers measure the
    // textarea width and emit a full-width rule instead.
    expect(body.value).toBe('\n\n' + core.makeDivider() + '\n\n')
    expect(body.value.startsWith('\n\n')).toBe(true)
    expect(body.value.endsWith('\n\n')).toBe(true)
  })

  it('exposes undo/redo through the action registry', () => {
    const { body, el, core } = setup('a')
    core.pushHistory()
    select(el, 1)
    body.value = 'ab'
    core.pushHistory()
    core.actions.undo()
    expect(body.value).toBe('a')
    core.actions.redo()
    expect(body.value).toBe('ab')
  })

  it('unknown action names are absent from the registry and dispatch as a no-op', () => {
    const { body, core } = setup('stable')
    // Both editor shells dispatch toolbar ids as `core.actions[name]?.()`
    // (EditorToolbar only emits a name), so an unknown id must not throw or
    // mutate the document.
    expect(core.actions['nope']).toBeUndefined()
    expect(() => core.actions['nope']?.()).not.toThrow()
    expect(body.value).toBe('stable')
  })

  it('every action is a safe no-op when no textarea is bound', () => {
    const body = ref('untouched')
    const core = useRichTextEditor({
      body,
      textarea: ref<HTMLTextAreaElement | null>(null),
    })
    for (const name of ['bold', 'h1', 'checklist', 'table', 'undo', 'redo']) {
      expect(() => core.actions[name]()).not.toThrow()
    }
    expect(body.value).toBe('untouched')
  })
})

describe('active-format detection', () => {
  function formatsAt(content: string, pos: number) {
    const { el, core } = setup(content)
    select(el, pos)
    core.computeFormats()
    return core.activeFormats.value
  }

  it('detects the heading level from the current line prefix', () => {
    expect(formatsAt('# Title\nbody', 4)).toContain('h1')
    expect(formatsAt('## Sub\nbody', 6)).toContain('h2')
    expect(formatsAt('### Deep', 8)).toContain('h3')
    // A heading deeper than the supported levels is not reported.
    expect(formatsAt('#### Deep', 8)).not.toContain('h3')
    // No false positive once the prefix is gone.
    expect(formatsAt('# Title\nbody', 10)).not.toContain('h1')
  })

  it('detects list flavours, quote and checklist from the line prefix', () => {
    expect(formatsAt('- item', 4)).toContain('ul')
    expect(formatsAt('* item', 4)).toContain('ul')
    expect(formatsAt('+ item', 4)).toContain('ul')
    expect(formatsAt('1. item', 5)).toContain('ol')
    expect(formatsAt('12. item', 5)).toContain('ol')
    expect(formatsAt('> quoted', 4)).toContain('quote')
    expect(formatsAt('- [ ] todo', 8)).toContain('checklist')
    expect(formatsAt('- [x] done', 8)).toContain('checklist')
    // A bare '-' line is not a list item (the marker needs a trailing space).
    expect(formatsAt('- item', 4)).not.toContain('checklist')
  })

  it('reports nothing for plain prose', () => {
    expect(formatsAt('just a plain sentence', 8).size).toBe(0)
  })

  it('detects highlight and text-align blocks near the cursor', () => {
    const content = '<mark>glow</mark> tail text'
    expect(formatsAt(content, 5)).toContain('highlight')
    expect(formatsAt('<div style="text-align: center">\nx\n</div>', 34)).toContain(
      'alignCenter',
    )
  })

  it('italic only lights up when the cursor sits between two asterisks', () => {
    // computeFormats needs before to end with a single '*' AND the text at the
    // cursor to start with '*' — i.e. the cursor inside an 'a **b' run. Inside
    // ordinary '*italic*' prose it stays dark, so the toolbar's active state
    // lags the document. Pinned so a fix flips these deliberately.
    expect(formatsAt('a **b', 3)).toContain('italic')
    expect(formatsAt('*italic*', 3).has('italic')).toBe(false)
  })

  it('does NOT report bold inside a plain **bold** span (known detection gap)', () => {
    // computeFormats only fires on bold when the cursor is squeezed between
    // two '**' runs (before.endsWith('**') && after.startsWith('**')); inside
    // ordinary '**bold**' prose it stays dark. Pinned here so a future fix
    // flips this test deliberately rather than silently.
    expect(formatsAt('**bold**', 4).has('bold')).toBe(false)
    expect(formatsAt('a ****b', 4)).toContain('bold')
  })

  it('clears detection when no textarea is bound', () => {
    const body = ref('# Title')
    const core = useRichTextEditor({
      body,
      textarea: ref<HTMLTextAreaElement | null>(null),
    })
    core.computeFormats()
    expect(core.activeFormats.value.size).toBe(0)
  })
})

describe('keyboard shortcuts (onShortcutKeydown)', () => {
  it('maps Ctrl/Cmd+B/I/K/U to bold, italic, code and strikethrough', () => {
    const { body, el, core } = setup('word')
    select(el, 0, 4)

    core.onShortcutKeydown(key('b', { ctrlKey: true }))
    expect(body.value).toBe('**word**')

    body.value = 'word'
    select(el, 0, 4)
    core.onShortcutKeydown(key('i', { ctrlKey: true }))
    expect(body.value).toBe('*word*')

    body.value = 'word'
    select(el, 0, 4)
    core.onShortcutKeydown(key('k', { ctrlKey: true }))
    expect(body.value).toBe('`word`')

    body.value = 'word'
    select(el, 0, 4)
    core.onShortcutKeydown(key('u', { ctrlKey: true }))
    expect(body.value).toBe('~~word~~')
  })

  it('treats Cmd on macOS like Ctrl (metaKey)', () => {
    const { body, el, core } = setup('word')
    select(el, 0, 4)
    core.onShortcutKeydown(key('b', { metaKey: true }))
    expect(body.value).toBe('**word**')
  })

  it('Ctrl+Z undoes and Ctrl+Y / Ctrl+Shift+Z redo', () => {
    const { body, el, core } = setup('a')
    core.pushHistory()
    select(el, 1)
    body.value = 'ab'
    core.pushHistory()

    core.onShortcutKeydown(key('z', { ctrlKey: true }))
    expect(body.value).toBe('a')

    core.onShortcutKeydown(key('y', { ctrlKey: true }))
    expect(body.value).toBe('ab')

    // Ctrl+Shift+Z is the other redo chord (and browsers deliver 'Z' with
    // Shift held) — both must redo, not undo.
    core.onShortcutKeydown(key('z', { ctrlKey: true }))
    expect(body.value).toBe('a')
    core.onShortcutKeydown(key('z', { ctrlKey: true, shiftKey: true }))
    expect(body.value).toBe('ab')
    core.onShortcutKeydown(key('z', { ctrlKey: true }))
    expect(body.value).toBe('a')
    core.onShortcutKeydown(key('Z', { ctrlKey: true }))
    expect(body.value).toBe('ab')
  })

  it('Ctrl+S calls the shell save handler and swallows the browser dialog', () => {
    const { el, core, onSave } = setup('a')
    const e = key('s', { ctrlKey: true })
    core.onShortcutKeydown(e)
    expect(e.defaultPrevented).toBe(true)
    expect(onSave).toHaveBeenCalledTimes(1)
    void el
  })

  it('Ctrl+F opens find, Escape closes it, Enter/Shift+Enter walk matches', () => {
    const { body, el, core } = setup('foo bar foo')
    core.onShortcutKeydown(key('f', { ctrlKey: true }))
    expect(core.showFind.value).toBe(true)

    core.onShortcutKeydown(key('Escape'))
    expect(core.showFind.value).toBe(false)

    core.showFind.value = true
    core.findQuery.value = 'foo'
    core.onShortcutKeydown(key('Enter'))
    expect(core.findIndex.value).toBe(0)
    // Shift+Enter walks backwards through the two matches.
    core.onShortcutKeydown(key('Enter', { shiftKey: true }))
    expect(core.findIndex.value).toBe(1)
    void body
    void el
  })

  it('Ctrl+Alt+H inserts a horizontal rule', () => {
    const { body, el, core } = setup('')
    select(el, 0)
    core.onShortcutKeydown(key('h', { ctrlKey: true, altKey: true }))
    expect(body.value.startsWith('\n\n')).toBe(true)
  })

  it('leaves unmodified keys and unmapped shortcuts alone', () => {
    const { body, el, core } = setup('word')
    const plain = key('b')
    core.onShortcutKeydown(plain)
    const unmapped = key('d', { ctrlKey: true })
    core.onShortcutKeydown(unmapped)
    expect(plain.defaultPrevented).toBe(false)
    expect(unmapped.defaultPrevented).toBe(false)
    expect(body.value).toBe('word')
    void el
  })

  it('Ctrl+Shift+B (uppercase key) still resolves through the map', () => {
    // Browsers deliver 'B' when Shift is held; the map lowercases the key.
    const { body, el, core } = setup('word')
    select(el, 0, 4)
    core.onShortcutKeydown(key('B', { ctrlKey: true, shiftKey: true }))
    expect(body.value).toBe('**word**')
  })
})

describe('auto-indent on Enter (onTextareaKeydown)', () => {
  function enterAfter(text: string, pos: number) {
    const { body, el, core } = setup(text)
    const e = key('Enter')
    el.selectionStart = el.selectionEnd = pos
    core.onTextareaKeydown(e)
    return { body, event: e }
  }

  it('continues a bullet list with the same marker', async () => {
    const { body, event } = enterAfter('- item', 6)
    expect(event.defaultPrevented).toBe(true)
    expect(body.value).toBe('- item\n- ')
    await nextTick()
  })

  it('continues an ordered list with the incremented number', () => {
    const { body } = enterAfter('1. one', 6)
    expect(body.value).toBe('1. one\n2. ')
  })

  it('keeps the indent depth of a nested list item', () => {
    const { body } = enterAfter('  - nested', 10)
    expect(body.value).toBe('  - nested\n  - ')
  })

  it('continues a checkbox with a fresh unchecked box', () => {
    expect(enterAfter('- [ ] task', 10).body.value).toBe('- [ ] task\n- [ ] ')
    expect(enterAfter('- [x] done', 10).body.value).toBe('- [x] done\n- [ ] ')
  })

  it('empties an unused list item instead of spawning another marker', () => {
    const { body } = enterAfter('- ', 2)
    expect(body.value).toBe('')
  })

  it('leaves plain prose alone (no preventDefault, no mutation)', () => {
    const { body, event } = enterAfter('plain line', 10)
    expect(event.defaultPrevented).toBe(false)
    expect(body.value).toBe('plain line')
  })
})

describe('Tab indent / outdent (onTextareaKeydown)', () => {
  it('inserts two spaces at the cursor', () => {
    const { body, el, core } = setup('ab')
    el.selectionStart = el.selectionEnd = 1
    core.onTextareaKeydown(key('Tab'))
    expect(body.value).toBe('a  b')
  })

  it('Shift+Tab removes two leading spaces from the current line', async () => {
    const { body, el, core } = setup('  indented\nplain')
    el.selectionStart = el.selectionEnd = 4
    core.onTextareaKeydown(key('Tab', { shiftKey: true }))
    await nextTick()
    expect(body.value).toBe('indented\nplain')
  })

  it('Shift+Tab on an unindented line is a no-op', () => {
    const { body, el, core } = setup('plain')
    el.selectionStart = el.selectionEnd = 2
    core.onTextareaKeydown(key('Tab', { shiftKey: true }))
    expect(body.value).toBe('plain')
  })
})

describe('input + find/replace plumbing', () => {
  it('onInput pushes history and flags the document dirty', () => {
    const { core, onChange } = setup('')
    core.onInput()
    expect(core.undoStack.value).toHaveLength(1)
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('replaceAll swaps every occurrence in one history step', () => {
    const { body, core, onChange } = setup('cat and cat and cat')
    core.pushHistory()
    core.findQuery.value = 'cat'
    core.replaceQuery.value = 'dog'
    core.replaceAll()
    expect(body.value).toBe('dog and dog and dog')
    expect(core.findCount.value).toBe(0)
    expect(core.undoStack.value.length).toBeGreaterThan(0)
    expect(onChange).not.toHaveBeenCalled() // replaceAll pushes history directly
    core.doUndo()
    expect(body.value).toBe('cat and cat and cat')
  })

  it('replaceOne swaps only the match at findIndex', async () => {
    const { body, core } = setup('a a a')
    core.findQuery.value = 'a'
    core.findIndex.value = 1
    core.replaceQuery.value = 'b'
    core.replaceOne()
    expect(body.value).toBe('a b a')
  })
})
