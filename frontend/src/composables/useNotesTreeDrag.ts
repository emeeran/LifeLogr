/**
 * useNotesTreeDrag — the pure half of the notebook tree's drag-and-drop.
 *
 * The rail is virtualized and rendered from `TreeItem`s, so the component owns
 * the DOM events and the store calls; deciding *what* a drop means lives here,
 * where it can be tested without layout.
 */

export interface TreeDragItem {
  kind: 'note' | 'folder'
  id: number
}

export interface FolderLink {
  id: number
  parent_id: number | null
}

export type DropTarget =
  | { kind: 'folder'; id: number }
  | { kind: 'unfiled' }
  | { kind: 'root' }
  /** Between-row insertion (DND-3). `beforeId` is the sibling the dragged row
   *  would land above (null = end of section). Notes insert only within their
   *  own section; folders only between siblings under the same parent. */
  | { kind: 'note-insert'; sectionKey: string; beforeId: number | null }
  | { kind: 'folder-insert'; parentId: number | null; beforeId: number | null }

export type DropResolution =
  | { action: 'note-to-folder'; noteId: number; folderId: number }
  | { action: 'note-to-unfiled'; noteId: number }
  | { action: 'folder-to-parent'; folderId: number; parentId: number }
  | { action: 'folder-to-root'; folderId: number }
  | { action: 'noop'; reason: string }
  | { action: 'cycle'; reason: string }

/**
 * True when `candidateId` is `ancestorId` or sits anywhere below it.
 * A depth guard makes a corrupt (already cyclic) folder list terminate.
 */
export function isDescendant(
  folders: readonly FolderLink[],
  ancestorId: number,
  candidateId: number,
): boolean {
  const byId = new Map(folders.map((f) => [f.id, f]))
  const seen = new Set<number>()
  let current: number | null = candidateId
  while (current != null) {
    if (current === ancestorId) return true
    if (seen.has(current)) return false
    seen.add(current)
    current = byId.get(current)?.parent_id ?? null
  }
  return false
}

/**
 * Plan a between-row reorder (DND-3): move `dragId` to just above `beforeId`
 * (or to the end when `beforeId` is null) and return a 1-based batch plan, or
 * null when the drop would change nothing (same slot, unknown ids, stale
 * target) — the component treats null as "nothing to send".
 */
export function computeReorder(
  section: readonly number[],
  dragId: number,
  beforeId: number | null,
): { id: number; sort_order: number }[] | null {
  const from = section.indexOf(dragId)
  if (from === -1) return null
  const rest = section.filter((id) => id !== dragId)
  const to = beforeId == null ? rest.length : rest.indexOf(beforeId)
  if (to === -1 || to === from) return null
  const next = [...rest.slice(0, to), dragId, ...rest.slice(to)]
  return next.map((id, i) => ({ id, sort_order: i + 1 }))
}

/**
 * Map a drag+drop pair onto a store mutation.
 *
 * `ctx.noteFolder` is the dragged note's current folder (null = unfiled);
 * `ctx.folders` is the flat folder list used for the cycle check. The component
 * cannot ask the backend first — it *silently* ignores a cyclic re-parent — so
 * the cycle must be caught here to give the user a reason.
 */
export function resolveDrop(
  item: TreeDragItem,
  target: DropTarget,
  ctx: { noteFolder: number | null; folders: readonly FolderLink[] },
): DropResolution {
  if (item.kind === 'note') {
    if (target.kind === 'folder') {
      if (ctx.noteFolder === target.id) {
        return { action: 'noop', reason: 'Already in this notebook' }
      }
      return { action: 'note-to-folder', noteId: item.id, folderId: target.id }
    }
    if (target.kind === 'unfiled' || target.kind === 'root') {
      if (ctx.noteFolder == null) {
        return { action: 'noop', reason: 'Already unfiled' }
      }
      return { action: 'note-to-unfiled', noteId: item.id }
    }
    return { action: 'noop', reason: 'Drop a note on a notebook or Unfiled' }
  }

  // Folder
  if (target.kind === 'folder') {
    if (item.id === target.id) {
      return { action: 'noop', reason: 'A notebook cannot contain itself' }
    }
    if (isDescendant(ctx.folders, item.id, target.id)) {
      return { action: 'cycle', reason: 'A notebook cannot move into itself' }
    }
    return { action: 'folder-to-parent', folderId: item.id, parentId: target.id }
  }
  if (target.kind === 'root') {
    const folder = ctx.folders.find((f) => f.id === item.id)
    if (folder && folder.parent_id == null) {
      return { action: 'noop', reason: 'Already at the top level' }
    }
    return { action: 'folder-to-root', folderId: item.id }
  }
  return { action: 'noop', reason: 'A notebook cannot be filed as a note' }
}
