/**
 * useInlineTags — `#`-triggered tag autocomplete for the shared editor.
 *
 * While typing in the textarea, a `#` followed by word chars opens a popover of
 * existing tags (filtered as you type, plus a "create new" row). Picking one
 * rewrites the in-progress `#query` token into `#name` and notifies the shell
 * (which ensures the Tag row exists). The shell wires `onInput`/`onKeydown` onto
 * the textarea; tag *linking* happens at save (see utils/tags.ts).
 */
import { computed, nextTick, ref, type Ref } from 'vue'
import { getCaretCoordinates } from '../utils/caretCoords'

export interface InlineTagOptions {
  body: Ref<string>
  textarea: Ref<HTMLTextAreaElement | null>
  /** A Ref/ComputedRef of available tags (only id + name are read). */
  tags: Readonly<{ value: { id: number; name: string }[] }>
  /** Fired after the body is mutated (so the shell can mark dirty). */
  onChange?: () => void
  /** Fired with the chosen tag name (so the shell can ensure the Tag exists). */
  onPick?: (name: string) => void
}

// Text immediately before the caret ending in an in-progress tag token.
const TOKEN_RE = /(?<![\w-])#([\w-]*)$/

export function useInlineTags(opts: InlineTagOptions) {
  const active = ref(false)
  const query = ref('')
  const start = ref(0) // index of the '#'
  const activeIndex = ref(0)
  const coords = ref({ x: 0, y: 0 })
  let closeTimer: ReturnType<typeof setTimeout> | null = null

  const rows = computed(() => {
    const q = query.value.trim().toLowerCase()
    const pool = opts.tags.value
    const matched = (
      q ? pool.filter((t) => t.name.toLowerCase().includes(q)) : pool
    ).slice(0, 8)
    const list = matched.map((t) => ({ id: t.id, name: t.name, create: false }))
    if (q && !matched.some((t) => t.name.toLowerCase() === q)) {
      list.push({ id: -1, name: query.value.trim(), create: true })
    }
    return list
  })

  function clampIndex() {
    activeIndex.value = Math.min(
      activeIndex.value,
      Math.max(0, rows.value.length - 1),
    )
  }

  function recompute() {
    const el = opts.textarea.value
    if (!el) return close()
    const pos = el.selectionStart
    const m = opts.body.value.slice(0, pos).match(TOKEN_RE)
    if (!m) return close()
    if (!active.value) {
      active.value = true
      activeIndex.value = 0
    }
    start.value = (m.index ?? 0) + (m[0].length - m[1].length - 1) // the '#'
    query.value = m[1]
    clampIndex()
    coords.value = getCaretCoordinates(el, pos)
  }

  function onInput() {
    if (closeTimer) {
      clearTimeout(closeTimer)
      closeTimer = null
    }
    recompute()
  }

  /** @returns true if the key was consumed (popover nav/commit/escape). */
  function onKeydown(e: KeyboardEvent): boolean {
    if (!active.value) return false
    const n = rows.value.length
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      e.stopPropagation()
      activeIndex.value = Math.min(activeIndex.value + 1, n - 1)
      return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      e.stopPropagation()
      activeIndex.value = Math.max(activeIndex.value - 1, 0)
      return true
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      const row = rows.value[activeIndex.value]
      commit(row ? row.name : query.value.trim())
      return true
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      close()
      return true
    }
    return false
  }

  function commit(name: string) {
    const cleaned = name.trim().replace(/^#/, '')
    if (!cleaned) return close()
    const el = opts.textarea.value
    const end = el ? el.selectionStart : opts.body.value.length
    const repl = '#' + cleaned
    opts.body.value =
      opts.body.value.slice(0, start.value) + repl + opts.body.value.slice(end)
    opts.onChange?.()
    close()
    opts.onPick?.(cleaned)
    if (el) {
      nextTick(() => {
        el.focus()
        el.selectionStart = el.selectionEnd = start.value + repl.length
      })
    }
  }

  function pick(name: string) {
    if (closeTimer) {
      clearTimeout(closeTimer)
      closeTimer = null
    }
    commit(name)
  }

  function close() {
    active.value = false
    query.value = ''
    activeIndex.value = 0
  }

  /** Call on textarea blur — delayed so a popover click lands first. */
  function scheduleClose() {
    closeTimer = setTimeout(close, 150)
  }

  return {
    active,
    query,
    rows,
    activeIndex,
    coords,
    onInput,
    onKeydown,
    pick,
    close,
    scheduleClose,
  }
}
