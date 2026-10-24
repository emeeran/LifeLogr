/**
 * useHotkey — app-wide keyboard shortcuts through one composable.
 *
 *   useHotkey('mod+k', () => ui.openSearchPalette())
 *   useHotkey('escape', close, { scope: 'modal', allowInInput: true })
 *
 * Every registration shares a single document-level keydown listener (installed
 * on first use), and `onScopeDispose` removes it when the owning component
 * unmounts — no more paired addEventListener/removeEventListener boilerplate.
 *
 * Combo grammar: '-'-separated modifiers + key, case-insensitive. `mod` means
 * Ctrl on Linux/Windows and Cmd on macOS, matching the rest of the app. A bare
 * key ('?', 'escape') matches on `e.key` alone.
 *
 * Scoping:
 *  • Typing guard — key events originating in an input/textarea/select or a
 *    contenteditable are ignored unless the registration passes
 *    `allowInInput: true`. That is what keeps the editor's in-textarea Ctrl+K
 *    (inline code) from also firing the global search palette.
 *  • Scope precedence — for a given combo, the most specific scope that has a
 *    handler wins and lower scopes are not run ('modal' → 'editor' → 'global').
 */
import { onScopeDispose } from 'vue'

export type HotkeyScope = 'modal' | 'editor' | 'global'

export interface HotkeyOptions {
  scope?: HotkeyScope
  /** Fire even when the event starts in a text field (default false). */
  allowInInput?: boolean
  /** preventDefault() before invoking the handler (default true). */
  preventDefault?: boolean
}

interface HotkeyEntry {
  handler: (e: KeyboardEvent) => void
  allowInInput: boolean
  preventDefault: boolean
}

// Most specific first: a modal's Esc beats an editor's, an editor's combo beats
// a global one.
const SCOPE_PRECEDENCE: HotkeyScope[] = ['modal', 'editor', 'global']
const MODIFIER_ORDER = ['mod', 'alt', 'shift'] as const
const MODIFIER_ALIASES: Record<string, string> = {
  mod: 'mod',
  ctrl: 'mod',
  control: 'mod',
  meta: 'mod',
  cmd: 'mod',
  command: 'mod',
  alt: 'alt',
  option: 'alt',
  shift: 'shift',
}
const KEY_ALIASES: Record<string, string> = {
  esc: 'escape',
  del: 'delete',
  ins: 'insert',
  return: 'enter',
  space: ' ',
  spacebar: ' ',
}
// Bare modifier presses carry no key of their own.
const BARE_MODIFIER_KEYS = new Set(['Control', 'Meta', 'Alt', 'Shift'])

/** registry[combo][scope] → handlers registered for it. */
const registry = new Map<string, Map<HotkeyScope, Set<HotkeyEntry>>>()
let listening = false

function normalizeCombo(combo: string): string {
  const mods = new Set<string>()
  let key = ''
  for (const part of combo.split('+')) {
    const p = part.trim().toLowerCase()
    if (!p) continue
    const mod = MODIFIER_ALIASES[p]
    if (mod) mods.add(mod)
    else key = KEY_ALIASES[p] ?? p
  }
  // A shifted punctuation key ('?') already encodes its shift in the character.
  if (mods.has('shift') && key.length === 1 && !/[a-z0-9]/.test(key))
    mods.delete('shift')
  return [...MODIFIER_ORDER.filter((m) => mods.has(m)), key].join('+')
}

function comboFromEvent(e: KeyboardEvent): string | null {
  if (BARE_MODIFIER_KEYS.has(e.key)) return null
  const isLetter = e.key.length === 1 && /[a-z]/i.test(e.key)
  const mods = new Set<string>()
  if (e.ctrlKey || e.metaKey) mods.add('mod')
  if (e.altKey) mods.add('alt')
  // For non-letters the character reflects the shift state ('?'), so adding a
  // shift modifier would double-count it.
  if (e.shiftKey && (isLetter || e.key.length > 1)) mods.add('shift')
  return [...MODIFIER_ORDER.filter((m) => mods.has(m)), e.key.toLowerCase()].join(
    '+',
  )
}

function isEditableTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null
  if (!t) return false
  const tag = t.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    t.isContentEditable
  )
}

function onKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented) return
  const combo = comboFromEvent(e)
  if (!combo) return
  const editable = isEditableTarget(e)
  const byScope = registry.get(combo)
  if (!byScope) return
  for (const scope of SCOPE_PRECEDENCE) {
    const entries = byScope.get(scope)
    if (!entries?.size) continue
    const matches = editable
      ? Array.from(entries).filter((en) => en.allowInInput)
      : Array.from(entries)
    if (!matches.length) continue
    // First scope with a live handler wins — lower scopes stay silent.
    for (const en of matches) {
      if (en.preventDefault) e.preventDefault()
      en.handler(e)
    }
    return
  }
}

function ensureListener() {
  if (listening || typeof document === 'undefined') return
  document.addEventListener('keydown', onKeydown)
  listening = true
}

export function useHotkey(
  combo: string,
  handler: (e: KeyboardEvent) => void,
  opts: HotkeyOptions = {},
) {
  const normalized = normalizeCombo(combo)
  const scope = opts.scope ?? 'global'
  const entry: HotkeyEntry = {
    handler,
    allowInInput: opts.allowInInput ?? false,
    preventDefault: opts.preventDefault ?? true,
  }

  let byScope = registry.get(normalized)
  if (!byScope) {
    byScope = new Map()
    registry.set(normalized, byScope)
  }
  let entries = byScope.get(scope)
  if (!entries) {
    entries = new Set()
    byScope.set(scope, entries)
  }
  entries.add(entry)
  ensureListener()

  onScopeDispose(() => {
    entries?.delete(entry)
    if (entries && !entries.size) byScope?.delete(scope)
    if (byScope && !byScope.size) registry.delete(normalized)
  })
}
