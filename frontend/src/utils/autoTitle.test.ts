import { describe, expect, it } from 'vitest'
import { deriveTitle } from './autoTitle'

describe('deriveTitle', () => {
  it('takes the first non-empty line and strips heading markers', () => {
    expect(deriveTitle('# Trip to Sundarbans\n\nWe left at dawn.')).toBe(
      'Trip to Sundarbans',
    )
    expect(deriveTitle('\n\n  ## Second try  ')).toBe('Second try')
  })

  it('strips list, quote and ordered-list markers', () => {
    expect(deriveTitle('- bought tickets')).toBe('bought tickets')
    expect(deriveTitle('> quoted opener')).toBe('quoted opener')
    expect(deriveTitle('3. third item')).toBe('third item')
  })

  it('keeps link and image labels, dropping the URLs', () => {
    expect(deriveTitle('[Planning doc](https://example.com/x)')).toBe(
      'Planning doc',
    )
    expect(deriveTitle('![Sunset over the lake](https://x/y.jpg)')).toBe(
      'Sunset over the lake',
    )
  })

  it('strips inline emphasis and code delimiters', () => {
    expect(deriveTitle('**Bold** and _em_ and `code`')).toBe(
      'Bold and em and code',
    )
  })

  it('drops stray HTML tags', () => {
    expect(deriveTitle('<p>Wrapped in html</p>')).toBe('Wrapped in html')
  })

  it('trims trailing punctuation and collapses whitespace', () => {
    expect(deriveTitle('A long   day...')).toBe('A long day')
    expect(deriveTitle('Done!')).toBe('Done')
  })

  it('keeps emoji and hashtags intact', () => {
    expect(deriveTitle('🎉 Party time')).toBe('🎉 Party time')
    expect(deriveTitle('#travel plans')).toBe('#travel plans')
  })

  it('returns nothing for photo-only or whitespace-only bodies', () => {
    expect(deriveTitle('![](/api/v1/media/1/file)')).toBe('')
    expect(deriveTitle('   \n\n\t\n')).toBe('')
    expect(deriveTitle('')).toBe('')
    expect(deriveTitle(null)).toBe('')
    expect(deriveTitle(undefined)).toBe('')
  })

  it('skips lines that become empty after stripping (rules, bare images)', () => {
    expect(deriveTitle('---\n![](x.png)\nReal first line')).toBe(
      'Real first line',
    )
  })

  it('truncates on a word boundary at the limit', () => {
    const body = `${'word '.repeat(40)}end`
    const out = deriveTitle(body, { max: 20 })
    expect(out.endsWith('…')).toBe(true)
    expect(Array.from(out).length).toBeLessThanOrEqual(21)
    expect(out).not.toContain('  ')
  })

  it('hard-truncates scripts without spaces instead of overflowing', () => {
    const body = '日記'.repeat(100)
    const out = deriveTitle(body, { max: 10 })
    expect(Array.from(out)).toHaveLength(11) // 10 code points + ellipsis
    expect(out.endsWith('…')).toBe(true)
  })

  it('does not split a surrogate pair', () => {
    const body = '🎉'.repeat(30)
    const out = deriveTitle(body, { max: 5 })
    expect(Array.from(out)).toHaveLength(6)
    expect(out).toBe('🎉🎉🎉🎉🎉…')
  })
})
