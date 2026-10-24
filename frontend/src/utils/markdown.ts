/**
 * The app's single markdown → sanitized-HTML pipeline.
 *
 * Every render site (editor preview, entry detail, scribble pad, changelog)
 * used to configure `marked` + `DOMPurify` itself; this module owns that setup
 * so the allowlist, GFM/breaks flags and the encrypted-block substitution can't
 * drift between them.
 *
 * ENC blocks (`<!--ENC{…}-->` — AES-encrypted text embedded in a body) are
 * replaced with a non-executable "🔒 Decrypt selection" chip. Encrypted blobs
 * are opaque ciphertext, so rendering them as a chip (instead of letting
 * DOMPurify drop the comment and the text silently vanish) is the readable
 * choice everywhere, including read-only surfaces that have no decrypt handler.
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.use({ gfm: true, breaks: true })

function encChip(enc: string): string {
  return `<span class="enc-block cursor-pointer bg-accent/10 text-accent px-1.5 py-0.5 rounded border border-accent/20 text-[11px] font-medium" data-enc="${enc}">🔒 Decrypt selection</span>`
}

/** Render untrusted markdown to HTML that is safe to inject with v-html. */
export function renderMarkdown(src: string): string {
  let html = marked(src) as string
  // Marked escapes HTML comments into entities; raw comments survive as-is.
  // Both forms must become the chip.
  html = html.replace(/&lt;!--ENC\{([^}]+)\}--&gt;/g, (_, enc) => encChip(enc))
  html = html.replace(/<!--ENC\{([^}]+)\}-->/g, (_, enc) => encChip(enc))
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-enc'] })
}
