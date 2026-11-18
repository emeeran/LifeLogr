import { describe, expect, it } from 'vitest'
import {
  NOTE_COLORS,
  contrastRatio,
  noteColor,
  noteColorLabel,
  noteColorValue,
} from './noteColors'

// The two surfaces a stripe/dot sits on. 3:1 is the WCAG minimum for
// non-text UI components, and is what makes an 8-colour palette usable as a
// label rather than decoration.
const LIGHT_SURFACE = '#ffffff'
const DARK_SURFACE = '#111827'

describe('noteColors palette', () => {
  it('has eight unique ids and values', () => {
    expect(NOTE_COLORS).toHaveLength(8)
    expect(new Set(NOTE_COLORS.map((c) => c.id)).size).toBe(8)
    expect(new Set(NOTE_COLORS.map((c) => c.value)).size).toBe(8)
  })

  it.each(NOTE_COLORS.map((c) => [c.label, c.value]))(
    '%s is distinguishable on both themes',
    (_label, value) => {
      expect(contrastRatio(value, LIGHT_SURFACE)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(value, DARK_SURFACE)).toBeGreaterThanOrEqual(3)
    },
  )

  it('resolves stored values case-insensitively', () => {
    expect(noteColor('#E11D48')?.label).toBe('Rose')
    expect(noteColorValue(' #059669 ')?.toLowerCase()).toBe('#059669')
    expect(noteColorLabel('#7C3AED')).toBe('Violet')
  })

  it('treats unset and unknown values as no colour', () => {
    expect(noteColor(null)).toBeNull()
    expect(noteColor('')).toBeNull()
    expect(noteColor('#123456')).toBeNull()
    expect(noteColorValue(null)).toBeNull()
    expect(noteColorLabel('not-a-colour')).toBeNull()
  })

  it('computes known contrast ratios', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1)
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })
})
