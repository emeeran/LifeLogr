import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { NoteListItem, NoteListResponse } from '../types'

const { list } = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('../api/notes', () => ({
  notesApi: { list: list },
}))

import { useNotesStore } from './notes'

function page(offset: number, size: number, total: number): NoteListResponse {
  const items = Array.from({ length: size }, (_, i) => ({
    id: offset + i + 1,
    title: `note ${offset + i + 1}`,
    body_snippet: '',
  })) as unknown as NoteListItem[]
  return { items, total, offset, limit: size }
}

/** The backend rejects `limit > 100` with a 422 (Query le=100) — the store's
 *  page-through-everything loop must never ask for more than that. */
const BACKEND_LIMIT_CAP = 100

beforeEach(() => {
  setActivePinia(createPinia())
  list.mockReset()
})

describe('notes store fetchNotes', () => {
  it('pages through the whole list until `total` is reached', async () => {
    list.mockImplementation(({ offset }: { offset: number }) => {
      if (offset === 0) return Promise.resolve(page(0, 100, 250))
      if (offset === 100) return Promise.resolve(page(100, 100, 250))
      return Promise.resolve(page(200, 50, 250))
    })

    const store = useNotesStore()
    await store.fetchNotes()

    expect(list.mock.calls.map((c) => c[0])).toEqual([
      { offset: 0, limit: 100 },
      { offset: 100, limit: 100 },
      { offset: 200, limit: 100 },
    ])
    expect(store.notes).toHaveLength(250)
    expect(store.total).toBe(250)
  })

  it('never requests a limit above the backend cap', async () => {
    list.mockResolvedValue(page(0, 100, 100))

    const store = useNotesStore()
    await store.fetchNotes()

    expect(list).toHaveBeenCalled()
    for (const [params] of list.mock.calls) {
      const p = params as { limit?: number }
      expect(p.limit ?? BACKEND_LIMIT_CAP).toBeLessThanOrEqual(
        BACKEND_LIMIT_CAP,
      )
    }
  })

  it('stops paging if the server stops returning items', async () => {
    list.mockImplementation(({ offset }: { offset: number }) =>
      Promise.resolve(offset === 0 ? page(0, 100, 500) : page(offset, 0, 500)),
    )

    const store = useNotesStore()
    await store.fetchNotes()

    expect(list).toHaveBeenCalledTimes(2)
    expect(store.notes).toHaveLength(100)
  })

  it('passes explicit offset/limit params through as a single fetch', async () => {
    list.mockResolvedValue(page(0, 20, 20))

    const store = useNotesStore()
    await store.fetchNotes({ offset: 40, limit: 20 })

    expect(list).toHaveBeenCalledTimes(1)
    expect(list).toHaveBeenCalledWith({ offset: 40, limit: 20 })
    expect(store.notes).toHaveLength(20)
  })
})
