import { describe, expect, it } from 'vitest'

import { isExternalHref } from './externalLink'

describe('isExternalHref', () => {
  it('accepts absolute http(s)/mailto/tel URLs (handed to the OS)', () => {
    expect(isExternalHref('https://example.com')).toBe(true)
    expect(isExternalHref('http://example.com/path')).toBe(true)
    expect(isExternalHref('mailto:user@example.com')).toBe(true)
    expect(isExternalHref('tel:+12025550100')).toBe(true)
  })

  it('rejects relative / anchor / query links so vue-router keeps handling them', () => {
    // Regression guard: treating these as external would preventDefault() the
    // click and break all in-app navigation (see the docstring).
    expect(isExternalHref('/settings')).toBe(false)
    expect(isExternalHref('notes/1')).toBe(false)
    expect(isExternalHref('#anchor')).toBe(false)
    expect(isExternalHref('?q=1')).toBe(false)
  })

  it('rejects empty / null-ish input', () => {
    expect(isExternalHref('')).toBe(false)
    expect(isExternalHref(null as unknown as string)).toBe(false)
    expect(isExternalHref(undefined as unknown as string)).toBe(false)
  })
})
