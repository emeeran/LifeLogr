/**
 * Markdown-body helpers for embedded media (journal editor).
 */

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Insert OCR-extracted text directly below an embedded image's markdown token,
 * as a visible plain-text blockquote (journal date standard decision: no
 * collapsible <details>, not at the cursor).
 *
 * Matches the first `![alt](url)` token whose url equals `url`. If the token
 * can't be found (hand-edited markdown, wrapped links), appends the blockquote
 * at the end of the body rather than dropping the text — with a console warn.
 */
export function insertOcrBelowImage(
  body: string,
  url: string,
  text: string,
): string {
  const quoted = text
    .trim()
    .split('\n')
    .map((l) => `> ${l.trim()}`)
    .join('\n')
  const tokenRe = new RegExp(`(!\\[[^\\]]*\\]\\(${escapeRe(url)}\\))`)
  const m = tokenRe.exec(body)
  if (!m) {
    console.warn('[markdownMedia] image token not found for OCR insert:', url)
    return `${body.replace(/\n*$/, '')}\n\n${quoted}`
  }
  return body.replace(tokenRe, `$1\n\n${quoted}`)
}

// ── Media display size (?w=&h= query params on the media URL) ────────────────
// The chosen preview size of a pasted image/video is persisted IN the note
// body by encoding it as `?w=<px>&h=<px>` on the media URL. The backend serve
// routes ignore query params, so the URL still resolves; the size travels
// with the note (backup/restore/export) without any server-side metadata.

export interface MediaSize {
  w: number
  h: number
}

/** Split a URL into bare url, query (without `?`) and `#hash`. Only a `?…`
 *  that appears before any `#` counts as the query. */
function splitUrl(url: string): { bare: string; query: string; hash: string } {
  const hashIdx = url.indexOf('#')
  const hash = hashIdx === -1 ? '' : url.slice(hashIdx)
  const noHash = hashIdx === -1 ? url : url.slice(0, hashIdx)
  const qIdx = noHash.indexOf('?')
  if (qIdx === -1) return { bare: noHash, query: '', hash }
  return { bare: noHash.slice(0, qIdx), query: noHash.slice(qIdx + 1), hash }
}

function parsePairs(query: string): Array<[string, string]> {
  return query
    .split('&')
    .filter(Boolean)
    .map((pair) => {
      const eq = pair.indexOf('=')
      return eq === -1 ? [pair, ''] : [pair.slice(0, eq), pair.slice(eq + 1)]
    })
}

/** Read the persisted `?w=&h=` size from a media URL. null unless both are
 *  present and positive integers (partial/invalid sizes are treated as
 *  "no size" rather than half-parsed). */
export function getMediaSize(url: string): MediaSize | null {
  const { query } = splitUrl(url)
  if (!query) return null
  let w: number | null = null
  let h: number | null = null
  for (const [key, value] of parsePairs(query)) {
    const k = key.toLowerCase()
    if (k === 'w' && w === null) w = Number(value)
    else if (k === 'h' && h === null) h = Number(value)
  }
  if (w === null || h === null) return null
  if (!Number.isInteger(w) || !Number.isInteger(h) || w <= 0 || h <= 0)
    return null
  return { w, h }
}

/** Return `url` with exactly one w/h pair: an existing pair is replaced (never
 *  duplicated), any other params keep their order and move before w/h, the
 *  hash is preserved. Idempotent. */
export function withSizeParams(url: string, w: number, h: number): string {
  const { bare, query, hash } = splitUrl(url)
  const kept = parsePairs(query)
    .filter(([k]) => k.toLowerCase() !== 'w' && k.toLowerCase() !== 'h')
    .map(([k, v]) => (v === '' ? k : `${k}=${v}`))
  return `${bare}?${[...kept, `w=${w}`, `h=${h}`].join('&')}${hash}`
}

/**
 * Rewrite the persisted size of the media token(s) matching `src` inside the
 * markdown body — both the `![alt](url)` form and the raw-HTML
 * `<img|video … src="url">` form (not `<audio>`, not plain links). `src` is
 * the DOM src and may already carry `?w=&h=`; matching is anchored on the bare
 * URL and tolerates any existing query (other params are preserved).
 * All tokens sharing the URL are rewritten (duplicate embeds share one size).
 * Returns the body unchanged — with a console warn — when nothing matches;
 * unlike `insertOcrBelowImage`, appending elsewhere would be wrong here.
 */
export function applyMediaSize(
  body: string,
  src: string,
  w: number,
  h: number,
): string {
  if (
    !Number.isInteger(w) ||
    w <= 0 ||
    !Number.isInteger(h) ||
    h <= 0
  ) {
    console.warn('[markdownMedia] applyMediaSize: invalid size', w, h)
    return body
  }
  const { bare } = splitUrl(src)
  const sized = (tail: string | undefined) =>
    withSizeParams(`${bare}${tail ?? ''}`, w, h)
  let changed = false
  const finish = (out: string): string => {
    if (!changed)
      console.warn('[markdownMedia] media token not found for size update:', bare)
    return out
  }
  const mdRe = new RegExp(
    `(!\\[[^\\]]*\\]\\()${escapeRe(bare)}(\\?[^)]*)?(\\))`,
    'g',
  )
  const afterMd = body.replace(mdRe, (_m, pre, tail, post) => {
    changed = true
    return `${pre}${sized(tail)}${post}`
  })
  const htmlRe = new RegExp(
    `(<(?:img|video)\\b[^>]*?\\ssrc\\s*=\\s*)(["'])${escapeRe(bare)}(\\?[^"']*)?\\2`,
    'gi',
  )
  return finish(
    afterMd.replace(htmlRe, (_m, pre, quote, tail) => {
      changed = true
      return `${pre}${quote}${sized(tail)}${quote}`
    }),
  )
}
