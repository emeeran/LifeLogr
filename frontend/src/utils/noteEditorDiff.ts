/**
 * Diff an editor's buffers against what was last loaded/saved.
 *
 * The save payload must be built from the loaded snapshot, not from the live
 * note prop: an external change (e.g. renaming the note from the rail) moves
 * the prop without touching the buffers, and diffing against the prop would
 * treat that as a local edit and write the stale buffer back — reverting the
 * rename. Fields that match the snapshot are simply omitted, and the backend
 * keeps the persisted value for any omitted field (null = keep).
 */
export interface NoteSavePayload {
  title?: string
  body?: string
}

export function noteSavePayload(
  title: string,
  loadedTitle: string,
  body: string,
  loadedBody: string,
): NoteSavePayload | null {
  const payload: NoteSavePayload = {}
  if (title !== loadedTitle) payload.title = title
  if (body !== loadedBody) payload.body = body
  return Object.keys(payload).length > 0 ? payload : null
}
