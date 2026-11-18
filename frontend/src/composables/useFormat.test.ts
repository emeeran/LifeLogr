import { describe, expect, it } from 'vitest'
import { formatDDMMYYYY, maskDDMMYYYY, parseDDMMYYYY } from './useFormat'

describe('formatDDMMYYYY', () => {
  it('formats a valid ISO date as dd-mm-yyyy', () => {
    expect(formatDDMMYYYY('2026-08-25')).toBe('25-08-2026')
  })

  it('prepends the weekday when asked', () => {
    // 2026-08-25 is a Tuesday
    expect(formatDDMMYYYY('2026-08-25', { weekday: 'short' })).toBe(
      'Tue 25-08-2026',
    )
    expect(formatDDMMYYYY('2026-08-25', { weekday: 'long' })).toBe(
      'Tuesday 25-08-2026',
    )
  })

  it('zero-pads day and month', () => {
    expect(formatDDMMYYYY('2026-01-05')).toBe('05-01-2026')
  })

  it('returns the input unchanged for non-ISO strings', () => {
    expect(formatDDMMYYYY('not-a-date')).toBe('not-a-date')
    expect(formatDDMMYYYY('')).toBe('')
  })

  it('returns the input unchanged for impossible dates', () => {
    expect(formatDDMMYYYY('2026-02-31')).toBe('2026-02-31')
    expect(formatDDMMYYYY('2026-13-01')).toBe('2026-13-01')
  })
})

describe('parseDDMMYYYY', () => {
  it('parses a valid dd-mm-yyyy into ISO', () => {
    expect(parseDDMMYYYY('25-08-2026')).toBe('2026-08-25')
  })

  it('accepts a fully typed mask with any separators', () => {
    // Users may type with or without dashes; the mask keeps positions stable.
    expect(parseDDMMYYYY('25/08/2026')).toBe('2026-08-25')
  })

  it('accepts short digit-only forms by strict position', () => {
    expect(parseDDMMYYYY('25082026')).toBe('2026-08-25')
  })

  it('rejects incomplete input', () => {
    expect(parseDDMMYYYY('25-08-202')).toBeNull()
    expect(parseDDMMYYYY('')).toBeNull()
    expect(parseDDMMYYYY('25-08')).toBeNull()
  })

  it('rejects impossible calendar dates', () => {
    expect(parseDDMMYYYY('32-01-2026')).toBeNull()
    expect(parseDDMMYYYY('31-02-2026')).toBeNull()
    expect(parseDDMMYYYY('00-01-2026')).toBeNull()
    expect(parseDDMMYYYY('01-13-2026')).toBeNull()
  })

  it('accepts 29 Feb on leap years and rejects it otherwise', () => {
    expect(parseDDMMYYYY('29-02-2024')).toBe('2024-02-29')
    expect(parseDDMMYYYY('29-02-2026')).toBeNull()
  })
})

describe('maskDDMMYYYY', () => {
  it('inserts dashes after day and month as digits are typed', () => {
    expect(maskDDMMYYYY('2')).toBe('2')
    expect(maskDDMMYYYY('25')).toBe('25')
    expect(maskDDMMYYYY('250')).toBe('25-0')
    expect(maskDDMMYYYY('2508')).toBe('25-08')
    expect(maskDDMMYYYY('25082')).toBe('25-08-2')
    expect(maskDDMMYYYY('25082026')).toBe('25-08-2026')
  })

  it('strips non-digits and caps at 8 digits', () => {
    expect(maskDDMMYYYY('25-08-2026')).toBe('25-08-2026')
    expect(maskDDMMYYYY('ab25/08/2026')).toBe('25-08-2026')
    expect(maskDDMMYYYY('250820269')).toBe('25-08-2026')
  })
})
