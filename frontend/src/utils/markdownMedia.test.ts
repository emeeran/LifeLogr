import { describe, expect, it } from 'vitest'
import { insertOcrBelowImage } from './markdownMedia'

describe('insertOcrBelowImage', () => {
  it('inserts the OCR text as a blockquote directly below the image token', () => {
    const body = 'before\n\n![pic](http://x/f.png)\n\nafter'
    const out = insertOcrBelowImage(body, 'http://x/f.png', 'hello world')
    expect(out).toBe(
      'before\n\n![pic](http://x/f.png)\n\n> hello world\n\nafter',
    )
  })

  it('escapes regex metacharacters in the url', () => {
    const url = 'http://x/a(b)+c.png?q=1&z=2'
    const body = `![p](${url})\n\nend`
    const out = insertOcrBelowImage(body, url, 'text')
    expect(out).toBe(`![p](${url})\n\n> text\n\nend`)
  })

  it('targets the first matching token when src repeats', () => {
    const body = '![a](u.png)\nmid\n![b](u.png)'
    const out = insertOcrBelowImage(body, 'u.png', 't')
    expect(out).toBe('![a](u.png)\n\n> t\nmid\n![b](u.png)')
  })

  it('appends at the end (with a warning) when the token is absent', () => {
    const body = 'no images here'
    const out = insertOcrBelowImage(body, 'missing.png', 't')
    expect(out).toBe('no images here\n\n> t')
  })

  it('keeps each OCR line as its own blockquote line', () => {
    const body = '![p](u.png)'
    const out = insertOcrBelowImage(body, 'u.png', 'line one\nline two')
    expect(out).toBe('![p](u.png)\n\n> line one\n> line two')
  })
})
