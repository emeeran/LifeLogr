import { describe, expect, it } from 'vitest'
import { countWords } from './text'

describe('countWords', () => {
  it('counts whitespace-run delimited words', () => {
    expect(countWords('one two  three\n\tfour')).toBe(4)
  })

  it('returns 0 for empty, blank, and nullish text', () => {
    expect(countWords('')).toBe(0)
    expect(countWords('   \n  ')).toBe(0)
    expect(countWords(null)).toBe(0)
    expect(countWords(undefined)).toBe(0)
  })

  it('ignores leading and trailing whitespace', () => {
    expect(countWords('  hello world  ')).toBe(2)
  })
})
