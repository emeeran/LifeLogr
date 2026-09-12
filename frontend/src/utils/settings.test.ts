import { describe, expect, it } from 'vitest'

import { clampRetention } from './settings'

describe('clampRetention', () => {
  it('clamps below the minimum', () => {
    expect(clampRetention(0)).toBe(1)
    expect(clampRetention(-5)).toBe(1)
  })

  it('clamps above the maximum', () => {
    expect(clampRetention(999)).toBe(100)
  })

  it('passes through in-range values', () => {
    expect(clampRetention(10)).toBe(10)
    expect(clampRetention(1)).toBe(1)
    expect(clampRetention(100)).toBe(100)
  })

  it('falls back to the minimum for non-finite input', () => {
    expect(clampRetention(NaN)).toBe(1)
    expect(clampRetention(Infinity)).toBe(1)
  })
})
