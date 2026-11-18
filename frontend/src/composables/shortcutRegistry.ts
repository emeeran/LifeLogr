/**
 * shortcutRegistry — the single source of truth for the app's keyboard
 * shortcuts. The cheatsheet dialog (KeyboardShortcutsDialog) renders this list,
 * so a binding only needs documenting here. Keep it in sync with the
 * `useHotkey()` registrations in AppShell.vue / ConfirmDialog.vue; the editors'
 * in-textarea bindings still live in useRichTextEditor (refactoring them onto
 * the composable is a deliberate follow-up — too invasive for one pass).
 */
export interface ShortcutEntry {
  /** Keys as displayed, e.g. ['Ctrl', 'K']. */
  keys: string[]
  label: string
}

export interface ShortcutGroup {
  title: string
  items: ShortcutEntry[]
}

export const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: 'Global',
    items: [
      { keys: ['Ctrl', 'K'], label: 'Search everything' },
      { keys: ['Ctrl', '.'], label: 'Toggle Zen Mode' },
      { keys: ['Ctrl', ','], label: 'Open Settings' },
      { keys: ['?'], label: 'Keyboard shortcuts (this dialog)' },
      { keys: ['Ctrl', '/'], label: 'Keyboard shortcuts (this dialog)' },
    ],
  },
  {
    title: 'Editors (journal + notes)',
    items: [
      // Notes save ONLY on Ctrl+S by design — hence its own entry.
      { keys: ['Ctrl', 'S'], label: 'Save now (notes save only this way)' },
      { keys: ['Ctrl', 'Z'], label: 'Undo' },
      { keys: ['Ctrl', 'Shift', 'Z'], label: 'Redo' },
      { keys: ['Ctrl', 'F'], label: 'Find & replace' },
      { keys: ['Ctrl', 'B'], label: 'Bold' },
      { keys: ['Ctrl', 'I'], label: 'Italic' },
      { keys: ['Ctrl', 'U'], label: 'Strikethrough' },
      { keys: ['Ctrl', 'K'], label: 'Inline code (while typing)' },
      { keys: ['Ctrl', 'Alt', 'H'], label: 'Insert horizontal rule' },
    ],
  },
  {
    title: 'Dialogs',
    items: [{ keys: ['Esc'], label: 'Close dialog / cancel' }],
  },
]
