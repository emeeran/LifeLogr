import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('renderMarkdown() — the shared pipeline', () => {
  it('renders GFM-style markdown (gfm + breaks are on)', () => {
    const html = renderMarkdown('# Hi\n\n- a\n- b')
    expect(html).toContain('<h1>Hi</h1>')
    expect(html).toContain('<li>a</li>')
  })

  it('turns an escaped ENC comment into a decrypt chip (how marked emits it)', () => {
    const html = renderMarkdown('before &lt;!--ENC{c2VjcmV0}--&gt; after')
    expect(html).toContain('enc-block')
    expect(html).toContain('data-enc="c2VjcmV0"')
    expect(html).toContain('Decrypt selection')
    // The ciphertext must not survive as text.
    expect(html).not.toContain('<!--ENC{c2VjcmV0}-->')
  })

  it('turns a raw ENC comment into the same chip', () => {
    const html = renderMarkdown('<!--ENC{abc}-->')
    expect(html).toContain('data-enc="abc"')
  })

  it('keeps the data-enc attribute (sanitizer allowlist)', () => {
    const html = renderMarkdown('<!--ENC{xyz}-->')
    expect(html).toContain('data-enc="xyz"')
  })

  it('still strips dangerous markup', () => {
    const html = renderMarkdown('<script>alert(1)</script>hello')
    expect(html).not.toContain('<script')
    expect(html).toContain('hello')
  })

  it('leaves ordinary markdown untouched by the ENC substitution', () => {
    expect(renderMarkdown('plain **bold**')).toContain('<strong>bold</strong>')
  })
})
