import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createTrackedObjectUrl,
  revokeTrackedObjectUrl,
  liveTrackedObjectUrlCount,
} from './blobUrl'

/**
 * happy-dom's URL has no blob-URL methods, so — like SecurityPanel.mount —
 * the suite stubs URL.createObjectURL / URL.revokeObjectURL with vi.stubGlobal
 * and pins the tracking contract: every created URL is remembered, every
 * revoke releases exactly that URL, and revokes are idempotent/no-op-safe.
 */

let seq = 0
const created: string[] = []
const revoked: string[] = []

beforeEach(() => {
  seq = 0
  created.length = 0
  revoked.length = 0
  vi.stubGlobal('URL', {
    ...globalThis.URL,
    createObjectURL: vi.fn(() => {
      const url = `blob:test-${++seq}`
      created.push(url)
      return url
    }),
    revokeObjectURL: vi.fn((url: string) => {
      revoked.push(url)
    }),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('tracked blob object URLs', () => {
  it('creates a URL from URL.createObjectURL and tracks it', () => {
    expect(liveTrackedObjectUrlCount()).toBe(0)
    const url = createTrackedObjectUrl(new Blob(['x']))
    expect(url).toBe('blob:test-1')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(liveTrackedObjectUrlCount()).toBe(1)
  })

  it('revokes the exact URL once and clears the tracking record', () => {
    const url = createTrackedObjectUrl(new Blob(['x']))
    revokeTrackedObjectUrl(url)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(url)
    expect(liveTrackedObjectUrlCount()).toBe(0)
  })

  it('is idempotent — a second revoke of the same URL is a no-op', () => {
    const url = createTrackedObjectUrl(new Blob(['x']))
    revokeTrackedObjectUrl(url)
    revokeTrackedObjectUrl(url)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
  })

  it('ignores URLs it did not create', () => {
    revokeTrackedObjectUrl('blob:foreign')
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })

  it('tolerates empty / missing URLs (unmount paths call unconditionally)', () => {
    expect(() => {
      revokeTrackedObjectUrl(null)
      revokeTrackedObjectUrl(undefined)
      revokeTrackedObjectUrl('')
    }).not.toThrow()
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })

  it('keeps independent URLs tracked independently', () => {
    const a = createTrackedObjectUrl(new Blob(['a']))
    const b = createTrackedObjectUrl(new Blob(['b']))
    expect(liveTrackedObjectUrlCount()).toBe(2)
    revokeTrackedObjectUrl(a)
    expect(revoked).toEqual([a])
    expect(liveTrackedObjectUrlCount()).toBe(1)
    revokeTrackedObjectUrl(b)
    expect(liveTrackedObjectUrlCount()).toBe(0)
  })
})
