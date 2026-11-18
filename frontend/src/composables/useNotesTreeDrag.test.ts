import { describe, expect, it } from 'vitest'
import {
  computeReorder,
  isDescendant,
  resolveDrop,
  type FolderLink,
} from './useNotesTreeDrag'

// Work (1) contains Projects (2), which contains Archive (3). Personal (4) is a sibling.
const FOLDERS: FolderLink[] = [
  { id: 1, parent_id: null },
  { id: 2, parent_id: 1 },
  { id: 3, parent_id: 2 },
  { id: 4, parent_id: null },
]

describe('isDescendant', () => {
  it('includes the folder itself', () => {
    expect(isDescendant(FOLDERS, 1, 1)).toBe(true)
  })

  it('walks the whole chain', () => {
    expect(isDescendant(FOLDERS, 1, 3)).toBe(true)
    expect(isDescendant(FOLDERS, 2, 3)).toBe(true)
  })

  it('is false across branches', () => {
    expect(isDescendant(FOLDERS, 3, 1)).toBe(false)
    expect(isDescendant(FOLDERS, 1, 4)).toBe(false)
  })

  it('terminates on a corrupt cyclic list', () => {
    const cyclic: FolderLink[] = [
      { id: 10, parent_id: 11 },
      { id: 11, parent_id: 10 },
    ]
    expect(isDescendant(cyclic, 99, 10)).toBe(false)
  })
})

describe('resolveDrop — notes', () => {
  it('files a note into a notebook', () => {
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'folder', id: 2 }, {
        noteFolder: null,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'note-to-folder', noteId: 7, folderId: 2 })
  })

  it('moves a note between notebooks', () => {
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'folder', id: 1 }, {
        noteFolder: 2,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'note-to-folder', noteId: 7, folderId: 1 })
  })

  it('is a no-op dropping into the current notebook', () => {
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'folder', id: 2 }, {
        noteFolder: 2,
        folders: FOLDERS,
      }).action,
    ).toBe('noop')
  })

  it('un-files on Unfiled and on the root target', () => {
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'unfiled' }, {
        noteFolder: 2,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'note-to-unfiled', noteId: 7 })
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'root' }, {
        noteFolder: 2,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'note-to-unfiled', noteId: 7 })
  })

  it('is a no-op when the note is already unfiled', () => {
    expect(
      resolveDrop({ kind: 'note', id: 7 }, { kind: 'unfiled' }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('noop')
  })
})

describe('resolveDrop — notebooks', () => {
  it('nests a notebook inside another', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 4 }, { kind: 'folder', id: 1 }, {
        noteFolder: null,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'folder-to-parent', folderId: 4, parentId: 1 })
  })

  it('rejects dropping a notebook on itself', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 1 }, { kind: 'folder', id: 1 }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('noop')
  })

  it('rejects a move into its own descendant', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 1 }, { kind: 'folder', id: 3 }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('cycle')
    expect(
      resolveDrop({ kind: 'folder', id: 2 }, { kind: 'folder', id: 3 }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('cycle')
  })

  it('moves a nested notebook to the top level', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 3 }, { kind: 'root' }, {
        noteFolder: null,
        folders: FOLDERS,
      }),
    ).toEqual({ action: 'folder-to-root', folderId: 3 })
  })

  it('is a no-op at the top level already', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 1 }, { kind: 'root' }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('noop')
  })

  it('refuses to file a notebook onto Unfiled', () => {
    expect(
      resolveDrop({ kind: 'folder', id: 1 }, { kind: 'unfiled' }, {
        noteFolder: null,
        folders: FOLDERS,
      }).action,
    ).toBe('noop')
  })
})

describe('computeReorder — between-row reorder plan (DND-3)', () => {
  it('moves a note before another (1-based sort_order plan)', () => {
    expect(computeReorder([1, 2, 3], 3, 1)).toEqual([
      { id: 3, sort_order: 1 },
      { id: 1, sort_order: 2 },
      { id: 2, sort_order: 3 },
    ])
  })

  it('moves a note to the end when beforeId is null', () => {
    expect(computeReorder([1, 2, 3], 1, null)).toEqual([
      { id: 2, sort_order: 1 },
      { id: 3, sort_order: 2 },
      { id: 1, sort_order: 3 },
    ])
  })

  it('is null when the item already sits at the target slot', () => {
    expect(computeReorder([1, 2, 3], 1, 2)).toBeNull()
    expect(computeReorder([1, 2, 3], 3, null)).toBeNull()
  })

  it('is null for a single-item section', () => {
    expect(computeReorder([7], 7, null)).toBeNull()
  })

  it('is null when the dragged id is not in the section', () => {
    expect(computeReorder([1, 2], 9, 1)).toBeNull()
  })

  it('is null when beforeId is not in the section (stale target)', () => {
    expect(computeReorder([1, 2], 1, 9)).toBeNull()
  })
})
