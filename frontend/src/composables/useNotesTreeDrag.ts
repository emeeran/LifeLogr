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
