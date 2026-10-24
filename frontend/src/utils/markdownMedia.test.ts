import { describe, expect, it, vi } from 'vitest'
import {
  applyMediaSize,
  getMediaSize,
  insertOcrBelowImage,
  withSizeParams,
} from './markdownMedia'

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

describe('getMediaSize', () => {
  it('parses ?w=&h= from the query', () => {
    expect(getMediaSize('http://x/f.png?w=400&h=300')).toEqual({ w: 400, h: 300 })
  })

  it('is order-independent and ignores other params', () => {
    expect(getMediaSize('u.png?h=300&fit=crop&w=400')).toEqual({ w: 400, h: 300 })
  })

  it('returns null when either param is missing or invalid', () => {
    expect(getMediaSize('u.png')).toBeNull()
    expect(getMediaSize('u.png?w=400')).toBeNull()
    expect(getMediaSize('u.png?w=abc&h=300')).toBeNull()
    expect(getMediaSize('u.png?w=-5&h=300')).toBeNull()
    expect(getMediaSize('u.png?w=0&h=300')).toBeNull()
  })

  it('does not treat a fragment as a query', () => {
    expect(getMediaSize('u.png#frag?w=400&h=300')).toBeNull()
  })
})

describe('withSizeParams', () => {
  it('appends w/h when the url has no query', () => {
    expect(withSizeParams('http://x/f.png', 400, 300)).toBe(
      'http://x/f.png?w=400&h=300',
    )
  })

  it('replaces an existing w/h pair without duplicating', () => {
    expect(withSizeParams('u.png?w=1&h=2', 400, 300)).toBe('u.png?w=400&h=300')
  })

  it('preserves other params and the hash', () => {
    expect(withSizeParams('u.png?download=1&w=9&h=9#top', 4, 3)).toBe(
      'u.png?download=1&w=4&h=3#top',
    )
  })

  it('is idempotent', () => {
    const once = withSizeParams('u.png', 400, 300)
    expect(withSizeParams(once, 400, 300)).toBe(once)
  })
})

describe('applyMediaSize', () => {
  it('appends the size to a markdown image token', () => {
    expect(applyMediaSize('before ![pic](u.png) after', 'u.png', 400, 300)).toBe(
      'before ![pic](u.png?w=400&h=300) after',
    )
  })

  it('accepts a src that already carries params (the editor call shape)', () => {
    expect(applyMediaSize('![p](u?w=1&h=2)', 'u?w=1&h=2', 400, 300)).toBe(
      '![p](u?w=400&h=300)',
    )
  })

  it('rewrites the raw-HTML video form, leaving other attributes intact', () => {
    const body =
      '\n<video controls preload="metadata" src="u.mp4" style="max-width:100%"></video>\n'
    expect(applyMediaSize(body, 'u.mp4', 400, 300)).toBe(
      '\n<video controls preload="metadata" src="u.mp4?w=400&h=300" style="max-width:100%"></video>\n',
    )
  })

  it('rewrites the single-quoted img form', () => {
    expect(applyMediaSize(`<img alt='a' src='u.png'>`, 'u.png', 4, 3)).toBe(
      `<img alt='a' src='u.png?w=4&h=3'>`,
    )
  })

  it('returns the body unchanged (with a warning) when no token matches', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(applyMediaSize('no media here', 'missing.png', 4, 3)).toBe(
      'no media here',
    )
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('only rewrites tokens matching the target url', () => {
    const body = '![a](u.png)\n![b](other.png)'
    expect(applyMediaSize(body, 'u.png', 4, 3)).toBe(
      '![a](u.png?w=4&h=3)\n![b](other.png)',
    )
  })

  it('rewrites every token sharing the bare url', () => {
    const body = '![a](u.png)\n![b](u.png)'
    expect(applyMediaSize(body, 'u.png', 4, 3)).toBe(
      '![a](u.png?w=4&h=3)\n![b](u.png?w=4&h=3)',
    )
  })

  it('does not rewrite plain links or audio elements', () => {
    const body = '[name](u.png)\n<audio controls src="u.png"></audio>'
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(applyMediaSize(body, 'u.png', 4, 3)).toBe(body)
    warn.mockRestore()
  })

  it('does not match a prefix of a longer url', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const body = '![a](f2.png)'
    expect(applyMediaSize(body, 'f.png', 4, 3)).toBe(body)
    warn.mockRestore()
  })

  it('keeps insertOcrBelowImage working on a sized token (OCR interop)', () => {
    const sized = applyMediaSize('![p](u.png)\n\nend', 'u.png', 400, 300)
    const out = insertOcrBelowImage(sized, withSizeParams('u.png', 400, 300), 't')
    expect(out).toBe('![p](u.png?w=400&h=300)\n\n> t\n\nend')
  })

  it('keeps the editors’ runOcr fallback regex capturing the full sized url', () => {
    // The editors' hardened fallback: `[^)]*<id>/file[^)]*` — a URL carrying
    // `?w=&h=` must be captured in full so insertOcrBelowImage can match it.
    const url = 'http://x/api/v1/notes/5/media/12/file?w=400&h=300'
    const m = `[pic](${url})`.match(new RegExp('\\]\\(([^)]*12/file[^)]*)\\)'))
    expect(m?.[1]).toBe(url)
  })
})
