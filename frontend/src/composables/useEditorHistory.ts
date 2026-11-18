import { ref, nextTick, type Ref } from 'vue'

interface HistoryEntry {
  content: string
  cursor: number
}

/** Depth cap. A journal entry's full undo history has no reason to keep 200
 *  full-body copies around. */
const MAX_ENTRIES = 60
/** Byte budget across the whole stack (~2 bytes/char for UTF-16). When the
 *  oldest snapshots would push the total past this, they are dropped first, so
 *  a handful of huge entries can't pin tens of MB of strings. Patch-based
 *  history (storing diffs instead of copies) remains the real fix. */
const MAX_BYTES = 5 * 1024 * 1024

function bytesOf(entry: HistoryEntry): number {
  return entry.content.length * 2
}

/** Keep the newest entries within the depth + byte budgets, always retaining at
 *  least one so undo still has a base to return to. */
function trimStack(stack: HistoryEntry[]): HistoryEntry[] {
  const kept = stack.length > MAX_ENTRIES ? stack.slice(-MAX_ENTRIES) : stack
  let total = 0
  let cut = kept.length // index of the oldest retained entry
  for (let i = kept.length - 1; i >= 0; i--) {
    const size = bytesOf(kept[i])
    if (total + size > MAX_BYTES && cut < kept.length) break
    total += size
    cut = i
  }
  return cut > 0 ? kept.slice(cut) : kept
}

export function useEditorHistory(
  body: Ref<string>,
  textarea: Ref<HTMLTextAreaElement | null>,
) {
  const undoStack = ref<HistoryEntry[]>([])
  const redoStack = ref<HistoryEntry[]>([])
  let lastPushTime = 0

  function pushHistory() {
    const el = textarea.value
    const cursor = el ? el.selectionStart : 0
    const now = Date.now()
    // Coalesce rapid edits into one undo step — but only once a base snapshot
    // AND at least one edit exist (length >= 2). Coalescing at length 1 would
    // overwrite the initial snapshot, making the first edit un-undoable.
    if (now - lastPushTime < 500 && undoStack.value.length >= 2) {
      const last = undoStack.value[undoStack.value.length - 1]
      if (last.content === body.value) return
      undoStack.value[undoStack.value.length - 1] = {
        content: body.value,
        cursor,
      }
      return
    }
    lastPushTime = now
    undoStack.value = trimStack([
      ...undoStack.value,
      { content: body.value, cursor },
    ])
    redoStack.value = []
  }

  function doUndo() {
    if (!undoStack.value.length) return
    const current = undoStack.value.pop()!
    redoStack.value.push(current)
    const prev = undoStack.value[undoStack.value.length - 1]
    if (prev) {
      body.value = prev.content
      nextTick(() => {
        if (textarea.value) {
          textarea.value.selectionStart = textarea.value.selectionEnd =
            prev.cursor
        }
      })
    } else {
      // Undid past the first snapshot — restore the empty/base state.
      body.value = ''
    }
  }

  function doRedo() {
    if (!redoStack.value.length) return
    const entry = redoStack.value.pop()!
    undoStack.value = trimStack([...undoStack.value, entry])
    body.value = entry.content
    nextTick(() => {
      if (textarea.value) {
        textarea.value.selectionStart = textarea.value.selectionEnd =
          entry.cursor
      }
    })
  }

  function resetHistory() {
    // Start a fresh undo stack (e.g. when the bound entity changes — a notes
    // sub-page switch — so undo never crosses that boundary). Zeroes the
    // coalesce timer so the next edit can't merge into a prior page's entry.
    undoStack.value = []
    redoStack.value = []
    lastPushTime = 0
    const el = textarea.value
    pushHistory()
    void el
  }

  return { undoStack, redoStack, pushHistory, doUndo, doRedo, resetHistory }
}
