import { describe, expect, it } from 'vitest'

import { noteSavePayload } from './noteEditorDiff'

describe('noteSavePayload', () => {
  it('returns null when nothing changed', () => {
    expect(noteSavePayload('T', 'T', 'B', 'B')).toBeNull()
  })

  it('sends only the title when only the title changed', () => {
    expect(noteSavePayload('New', 'Old', 'B', 'B')).toEqual({ title: 'New' })
  })

  it('sends only the body when only the body changed', () => {
    expect(noteSavePayload('T', 'T', 'New body', 'Old body')).toEqual({
      body: 'New body',
    })
  })

  it('sends both when both changed', () => {
    expect(noteSavePayload('New', 'Old', 'New body', 'Old body')).toEqual({
      title: 'New',
      body: 'New body',
    })
  })

  it('omits the title when it matches the loaded snapshot even though the note title moved', () => {
    // Regression: renaming a note from the rail updates props.note.title but
    // not the editor's buffers. The save payload must be diffed against the
    // loaded snapshot — against props it would treat the rename as a local
    // edit and write the stale buffer back, reverting the rename.
    expect(noteSavePayload('Old Title', 'Old Title', 'B', 'B')).toBeNull()
  })
})
