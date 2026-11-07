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

/**
 * Entry media has a cached ≤640 px thumbnail endpoint. Preview images are
 * decoded at intrinsic size otherwise, and a long media-heavy entry can push
 * WebKitWebProcess into the gigabytes (a blank window on the desktop build).
 * An explicit `?w=` above the thumbnail size opts out — the user asked for a
 * larger rendering, so the full source is what they get. Sizes at or below 640
 * still use the thumbnail (that is what new inserts get).
 */
function previewImageSrc(href: string): string {
  const requested = /[?&]w=(\d+)/.exec(href)
  if (requested && Number(requested[1]) > 640) return href
  return href.replace(/\/api\/v1\/media\/(\d+)\/file(\?.*)?$/, '/api/v1/media/$1/thumb')
}

function escAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

marked.use({
  gfm: true,
  breaks: true,
  renderer: {
    image({ href, title, text }) {
      const attrs = [
        `src="${escAttr(previewImageSrc(href))}"`,
        `alt="${escAttr(text ?? '')}"`,
        'loading="lazy"',
        'decoding="async"',
      ]
      if (title) attrs.push(`title="${escAttr(title)}"`)
      return `<img ${attrs.join(' ')}>`
    },
  },
})

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
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['data-enc', 'loading', 'decoding'],
  })
}
