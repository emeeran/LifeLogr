import { ref } from 'vue'
import { mediaApi } from '../api/media'
import type { MediaResponse } from '../types'

export function useAttachments(
  hasEntry: () => boolean,
  editingEntryId: () => number | null,
  refreshAll: () => void
) {
  const attachments = ref<MediaResponse[]>([])

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

  return { attachments, loadAttachments, handleFileUpload, removeAttachment }
}
