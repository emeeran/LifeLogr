/**
 * deriveTitle — build a note/entry title from the first meaningful line of a
 * markdown body.
 *
 * Used only when the title field is empty and the user has not touched it, so
 * it must never invent text: a body of images (no alt), whitespace or HTML
 * scaffolding returns `''` and leaves the record untitled.
 *
 * Markdown is stripped rather than rendered: a heading's `#`, a list bullet, a
 * quote marker, emphasis delimiters and link syntax are formatting, not title
 * content. Truncation happens on a word boundary (or hard at the limit for
 * scripts without spaces) and is marked with an ellipsis.
 */

export interface DeriveTitleOptions {
  /** Maximum characters kept, before the ellipsis. Default 120. */
  max?: number
}

const HEADING_RE = /^#{1,6}\s+/
const QUOTE_RE = /^>\s?/
const LIST_RE = /^(?:[-*+]|\d+[.)])\s+/
const IMAGE_RE = /!\[([^\]]*)\]\([^)]*\)/g
const LINK_RE = /\[([^\]]+)\]\([^)]*\)/g
const INLINE_MARKUP_RE = /[*_~`]+/g
const HTML_TAG_RE = /<[^>]+>/g
const TRAILING_PUNCT_RE = /[\s.;:,!?\-–—]+$/
const WHITESPACE_RE = /\s+/g

function truncate(value: string, max: number): string {
  const chars = Array.from(value)
  if (chars.length <= max) return value
  const cut = chars.slice(0, max).join('')
  // Prefer a word boundary, but never cut back more than ~40% of the limit.
  const space = cut.lastIndexOf(' ')
  const base = space > Math.floor(max * 0.6) ? cut.slice(0, space) : cut
  return `${base.replace(/\s+$/, '')}…`
}

/** First line of *body* that carries text after markdown is stripped. */
export function deriveTitle(
  body: string | null | undefined,
  opts: DeriveTitleOptions = {},
): string {
  const max = opts.max ?? 120
  if (!body) return ''

  const lines = body.replace(/\r\n?/g, '\n').split('\n')
  for (const raw of lines) {
    let line = raw.trim()
    if (!line) continue

    line = line.replace(HEADING_RE, '')
    line = line.replace(QUOTE_RE, '')
    line = line.replace(LIST_RE, '')
    // Images and links keep their human-readable label; a bare image with no
    // alt text contributes nothing and falls through to the next line.
    line = line.replace(IMAGE_RE, '$1')
    line = line.replace(LINK_RE, '$1')
    line = line.replace(INLINE_MARKUP_RE, '')
    line = line.replace(HTML_TAG_RE, '')
    line = line.replace(WHITESPACE_RE, ' ').trim()
    line = line.replace(TRAILING_PUNCT_RE, '').trim()

    if (line) return truncate(line, max)
  }
  return ''
}
