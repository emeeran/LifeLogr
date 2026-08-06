import { ref } from "vue";
import { mediaApi } from "../api/media";
import type { MediaResponse } from "../types";

export function useAttachments(
  hasEntry: () => boolean,
  editingEntryId: () => number | null,
  refreshAll: () => void,
) {
  const attachments = ref<MediaResponse[]>([]);

  function errMsg(e: unknown) {
    return e instanceof Error ? e.message : String(e);
  }

  function isImage(t: string) {
    return t === "image" || t.startsWith("image/");
  }

  async function loadAttachments() {
    if (!hasEntry()) {
      attachments.value = [];
      return;
    }
    try {
      // Images live inline in the entry body (see EntryEditor.embedImageFile);
      // the side panel/grid surfaces only non-image attachments.
      const all = await mediaApi.listByEntry(editingEntryId()!);
      attachments.value = all.filter((m) => !isImage(m.media_type));
    } catch {
      /* ignore */
    }
  }

  async function handleFileUpload(files: FileList | null) {
    if (!files?.length || !hasEntry()) return;
    for (const file of Array.from(files)) {
      try {
        const m = await mediaApi.upload(editingEntryId()!, file);
        attachments.value.push(m);
      } catch (e: unknown) {
        alert(`Upload failed: ${errMsg(e)}`);
      }
    }
    refreshAll();
  }

  async function removeAttachment(id: number) {
    try {
      await mediaApi.delete(id);
      attachments.value = attachments.value.filter((m) => m.id !== id);
      refreshAll();
    } catch (e: unknown) {
      alert(`Delete failed: ${errMsg(e)}`);
    }
  }

  return { attachments, loadAttachments, handleFileUpload, removeAttachment };
}
