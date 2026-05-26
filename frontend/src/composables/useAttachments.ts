import { ref, type Ref } from 'vue'
import { mediaApi } from '../api/media'
import { runOCR } from '../api/ai'
import type { MediaResponse } from '../types'

export function useAttachments(
  hasEntry: () => boolean,
  editingEntryId: () => number | null,
  refreshAll: () => void
) {
  const attachments = ref<MediaResponse[]>([])
  const aiProcessing = ref(false)

  function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e) }

  async function loadAttachments() {
    if (!hasEntry()) { attachments.value = []; return }
    try {
      attachments.value = await mediaApi.listByEntry(editingEntryId()!)
    } catch { /* ignore */ }
  }

  async function handleFileUpload(files: FileList | null) {
    if (!files?.length || !hasEntry()) return
    for (const file of Array.from(files)) {
      try {
        const m = await mediaApi.upload(editingEntryId()!, file)
        attachments.value.push(m)
      } catch (e: unknown) {
        alert(`Upload failed: ${errMsg(e)}`)
      }
    }
    refreshAll()
  }

  async function removeAttachment(id: number) {
    try {
      await mediaApi.delete(id)
      attachments.value = attachments.value.filter(m => m.id !== id)
      refreshAll()
    } catch (e: unknown) {
      alert(`Delete failed: ${errMsg(e)}`)
    }
  }

  async function runOcrTool(mediaId: number, body: Ref<string>, pushHistory: () => void, markDirty: () => void) {
    aiProcessing.value = true
    try {
      const res = await runOCR(mediaId)
      if (res.extracted_text) {
        body.value += `\n\n[OCR Text]\n${res.extracted_text}`
        pushHistory()
        markDirty()
        alert('Text extracted and appended to entry.')
      } else {
        alert('No text detected in image.')
      }
    } catch (e: unknown) {
      alert(`OCR failed: ${errMsg(e)}`)
    } finally {
      aiProcessing.value = false
    }
  }

  return { attachments, aiProcessing, loadAttachments, handleFileUpload, removeAttachment, runOcrTool }
}
