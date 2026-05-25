import { ref } from 'vue'

const ACCEPTED_TYPES = [
  'image/', 'video/', 'audio/',
  'application/pdf', 'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain', 'text/markdown', 'text/csv',
  'application/json',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]

function isAcceptedType(file: File): boolean {
  // Check MIME type
  for (const t of ACCEPTED_TYPES) {
    if (file.type.startsWith(t)) return true
  }
  // Check extension fallback
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  return ['pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'xlsx', 'json'].includes(ext)
}

export function useDragDrop() {
  const isDragging = ref(false)
  let dragCounter = 0 // Track child elements to prevent flicker

  function onDragenter(e: DragEvent) {
    e.preventDefault()
    dragCounter++
    if (e.dataTransfer?.types.includes('Files')) {
      isDragging.value = true
    }
  }

  function onDragover(e: DragEvent) {
    e.preventDefault()
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy'
    }
  }

  function onDragleave(e: DragEvent) {
    e.preventDefault()
    dragCounter--
    if (dragCounter <= 0) {
      dragCounter = 0
      isDragging.value = false
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    dragCounter = 0
    isDragging.value = false

    const files = e.dataTransfer?.files
    if (!files?.length) return

    // Filter to accepted types only
    const accepted = Array.from(files).filter(isAcceptedType)
    return accepted
  }

  const handlers = { onDragenter, onDragover, onDragleave, onDrop }

  return { isDragging, handlers }
}
