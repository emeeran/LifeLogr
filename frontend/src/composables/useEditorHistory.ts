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
    if (now - lastPushTime < 500 && undoStack.value.length > 0) {
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
    if (undoStack.value.length < 2) return
    const current = undoStack.value.pop()!
    redoStack.value.push(current)
    const prev = undoStack.value[undoStack.value.length - 1]
    body.value = prev.content
    nextTick(() => {
      if (textarea.value) {
        textarea.value.selectionStart = textarea.value.selectionEnd = prev.cursor
      }
    })
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

  return { undoStack, redoStack, pushHistory, doUndo, doRedo }
}
