/**
 * useDraftRecovery — a crash-recovery mirror for the notes editor.
 *
 * Notes persist ONLY on explicit Save (Ctrl+S) by design, so a crash / force-
 * quit with unsaved edits loses them. This composable keeps a debounced
 * localStorage mirror of the editor buffers and, on the next mount, surfaces a
 * stored draft that differs from the persisted note so the user can restore or
 * discard it. It is deliberately NOT an autosave: nothing here writes to the
 * backend, and the mirror is cleared the moment a save succeeds.
 *
 * PRIVACY: this app is privacy-first and note bodies can be AES-256-GCM
 * encrypted. The encrypted main body is ciphertext on disk — mirroring the
 * *plaintext the user is typing* into localStorage would be a regression, so
 * `opts.encrypted` gates every write (and any stale draft is dropped on mount).
 *
 *   const drafts = useDraftRecovery({ … })
 *   drafts.clear()               // after a successful save
 *   drafts.flush()               // before swapping the buffers (page switch)
 */
import { ref, onUnmounted } from 'vue'
import { watchDebounced } from '@vueuse/core'

export interface NoteDraft {
  noteId: number
  /** null = the note's Main tab; otherwise the NotePage id the draft belongs to. */
  pageId: number | null
  title: string
  body: string
  savedAt: number
}

export interface DraftRecoveryOptions {
  noteId: () => number
  pageId: () => number | null
  title: () => string
  body: () => string
  /** Persisted content the buffers were loaded from — the differ's baseline. */
  savedTitle: () => string
  savedBody: () => string
  /** True while the edited source is encrypted — its content is never mirrored. */
  encrypted: () => boolean
  /** Writes a restored draft into the editor buffers (still dirty — not saved). */
  applyDraft: (draft: NoteDraft) => void
}

const STORAGE_KEY = 'lifelogr-note-drafts'
const DEBOUNCE_MS = 1000
// Upper bound on a stalled write while typing continuously, so a crash can
// never lose more than a few seconds of work.
const MAX_WAIT_MS = 3000
// Mirrors are a safety net, not an archive: drop drafts older than two weeks.
const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000

function draftKey(noteId: number, pageId: number | null): string {
  return `${noteId}:${pageId ?? 'main'}`
}

function readAll(): Record<string, NoteDraft> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const now = Date.now()
    const out: Record<string, NoteDraft> = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      const d = v as Partial<NoteDraft>
      if (
        typeof d.noteId === 'number' &&
        typeof d.title === 'string' &&
        typeof d.body === 'string' &&
        typeof d.savedAt === 'number' &&
        now - d.savedAt < MAX_AGE_MS
      ) {
        out[k] = {
          noteId: d.noteId,
          pageId: d.pageId ?? null,
          title: d.title,
          body: d.body,
          savedAt: d.savedAt,
        }
      }
    }
    return out
  } catch {
    // Corrupt/unavailable storage must never block the editor.
    return {}
  }
}

function writeAll(all: Record<string, NoteDraft>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all))
  } catch {
    /* quota / privacy mode — the editor keeps working without the mirror */
  }
}

export function useDraftRecovery(opts: DraftRecoveryOptions) {
  // Set on mount when a stored draft differs from the persisted note — the
  // editor renders its restore/discard prompt for it.
  const pendingDraft = ref<NoteDraft | null>(null)

  function key() {
    return draftKey(opts.noteId(), opts.pageId())
  }

  function store(draft: NoteDraft | null) {
    const all = readAll()
    const k = key()
    if (draft) all[k] = draft
    else delete all[k]
    writeAll(all)
  }

  /** True when the buffers hold content the note doesn't have yet. */
  function isUnsaved() {
    return (
      opts.title() !== opts.savedTitle() || opts.body() !== opts.savedBody()
    )
  }

  /** Mirror the buffers now (no debounce) — used before a buffer swap/unmount. */
  function flush() {
    if (opts.encrypted() || !isUnsaved()) return
    if (!opts.title() && !opts.body()) return
    store({
      noteId: opts.noteId(),
      pageId: opts.pageId(),
      title: opts.title(),
      body: opts.body(),
      savedAt: Date.now(),
    })
  }

  // Surface a stored draft for this note/page whose content differs from what
  // is persisted — i.e. work a crash would have lost. Encrypted notes are
  // never mirrored, so drop any stale plaintext draft instead of prompting.
  const keyOfMount = key()
  if (opts.encrypted()) {
    store(null)
  } else {
    const stored = readAll()[keyOfMount]
    if (
      stored &&
      (stored.title !== opts.savedTitle() ||
        stored.body !== opts.savedBody()) &&
      (stored.title || stored.body)
    ) {
      pendingDraft.value = stored
    }
  }

  // Debounced mirror of the live buffers. maxWait keeps the mirror fresh even
  // during continuous typing, so a crash costs at most a few seconds.
  watchDebounced(
    [() => opts.title(), () => opts.body()],
    () => {
      if (pendingDraft.value) return // prompt unresolved — don't overwrite it
      if (isUnsaved()) flush()
      else store(null) // edits undone/saved → the mirror is obsolete
    },
    { debounce: DEBOUNCE_MS, maxWait: MAX_WAIT_MS },
  )

  /** Called after a successful save — there is nothing left to recover. */
  function clear() {
    pendingDraft.value = null
    store(null)
  }

  /** Put the draft into the editor buffers; it stays dirty (not saved). */
  function restore() {
    const d = pendingDraft.value
    if (!d) return
    pendingDraft.value = null
    store(null)
    opts.applyDraft(d)
  }

  /** Throw the draft away. */
  function discard() {
    pendingDraft.value = null
    store(null)
  }

  onUnmounted(flush)

  return { pendingDraft, flush, clear, restore, discard }
}
