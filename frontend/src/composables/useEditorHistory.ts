import { ref, nextTick, type Ref } from 'vue'

interface HistoryEntry { content: string; cursor: number }

export function useEditorHistory(body: Ref<string>, textarea: Ref<HTMLTextAreaElement | null>) {
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
      undoStack.value[undoStack.value.length - 1] = { content: body.value, cursor }
      return
    }
    lastPushTime = now
    undoStack.value.push({ content: body.value, cursor })
    if (undoStack.value.length > 200) undoStack.value.shift()
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
          textarea.value.selectionStart = textarea.value.selectionEnd = prev.cursor
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
    undoStack.value.push(entry)
    body.value = entry.content
    nextTick(() => {
      if (textarea.value) {
        textarea.value.selectionStart = textarea.value.selectionEnd = entry.cursor
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
