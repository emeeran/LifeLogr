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
export function insertOcrBelowImage(body: string, url: string, text: string): string {
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
