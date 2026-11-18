/**
 * usePasteMedia — clipboard-media paste for editor bodies.
 *
 * Handles the paste event on the editor <textarea>: image/audio/video files
 * in the clipboard are routed to the caller's `upload` (editor-specific);
 * HTML/delimited text is converted to a markdown table when it looks like
 * one; plain text falls through to the default browser paste.
 *
 * In the Tauri build, WebKitGTK only surfaces clipboard images reliably via
 * the Tauri clipboard plugin, so after the synchronous text check we fall
 * back to `readImage()` → canvas → PNG File (extracted from NoteEditor).
 */
import { isTauri } from '../api/client'

export interface PasteMediaOptions {
  /** Upload a media File and embed it (editor owns the markdown policy).
   *  Return false to decline (e.g. encrypted body) and keep default paste. */
  uploadMedia: (file: File) => Promise<boolean | void>
  /** Insert markdown at the cursor (table conversion path). */
  applyText: (text: string) => void
}

export function usePasteMedia(opts: PasteMediaOptions) {
  const { uploadMedia, applyText } = opts

  async function onPaste(e: ClipboardEvent) {
    if (isTauri) {
      await onPasteTauri(e)
      return
    }
    const cd = e.clipboardData
    if (!cd) return
    const media: File[] = []
    for (const it of cd.items) {
      if (
        it.kind === 'file' &&
        (it.type.startsWith('image/') ||
          it.type.startsWith('audio/') ||
          it.type.startsWith('video/'))
      ) {
        const f = it.getAsFile()
        if (f) media.push(f)
      }
    }
    if (media.length) {
      e.preventDefault()
      for (const f of media) await uploadMedia(f)
      return
    }
    const html = cd.getData('text/html')
    if (html && /<table[\s>]/i.test(html)) {
      const md = htmlTableToMarkdown(html)
      if (md) {
        e.preventDefault()
        applyText('\n' + md + '\n')
        return
      }
    }
    const text = cd.getData('text/plain')
    if (
      text &&
      text.includes('\n') &&
      (text.includes('\t') || /^[^\n]*,[^\n]*\n/m.test(text))
    ) {
      const md = delimitedToMarkdown(text)
      if (md) {
        e.preventDefault()
        applyText('\n' + md + '\n')
      }
    }
  }

  async function onPasteTauri(e: ClipboardEvent) {
    const cd = e.clipboardData
    const cdImage = cd
      ? Array.from(cd.items).find(
          (it) => it.kind === 'file' && it.type.startsWith('image/'),
        )
      : null
    if (cdImage) {
      e.preventDefault()
      const f = cdImage.getAsFile()
      if (f) await uploadMedia(f)
      return
    }
    // Read text synchronously — the paste event's clipboardData is only
    // reliable before any `await` (WebKitGTK drops it once the handler goes
    // async), so the common text-paste path must not depend on the async
    // image read below.
    const text = cd?.getData('text/plain') ?? ''
    if (text) {
      e.preventDefault()
      applyText(text)
      return
    }
    // No text in the event — the system clipboard may hold an image WebKitGTK
    // didn't surface as a file. Fall back to the Tauri clipboard plugin.
    e.preventDefault()
    try {
      const { readImage } = await import('@tauri-apps/plugin-clipboard-manager')
      const img = await readImage()
      if (img) await uploadClipImage(img)
    } catch {
      /* clipboard has no image */
    }
  }

  async function uploadClipImage(img: {
    rgba: () => Promise<Uint8Array>
    size: () => Promise<{ width: number; height: number }>
  }) {
    const rgba = await img.rgba()
    const { width, height } = await img.size()
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const imgData = ctx.createImageData(width, height)
    imgData.data.set(rgba)
    ctx.putImageData(imgData, 0, 0)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/png'),
    )
    if (!blob) return
    await uploadMedia(new File([blob], 'pasted.png', { type: 'image/png' }))
  }

  return { onPaste, onPasteTauri }
}

// ── Paste-to-table helpers ───────────────────────────────────────────────────

function htmlTableToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return ''
  const grid = Array.from(table.querySelectorAll('tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td,th')).map((c) =>
      (c.textContent || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' '),
    ),
  )
  return gridToMarkdown(grid)
}

function delimitedToMarkdown(text: string): string {
  const lines = text
    .replace(/\r/g, '')
    .split('\n')
    .filter((l) => l.length > 0)
  if (lines.length < 2) return ''
  const delim = lines[0].includes('\t') ? '\t' : ','
  return gridToMarkdown(lines.map((l) => l.split(delim)))
}

function gridToMarkdown(grid: string[][]): string {
  if (!grid.length || !grid[0]?.length) return ''
  const cols = Math.max(...grid.map((r) => r.length))
  const norm = grid.map((r) => {
    const row = [...r]
    while (row.length < cols) row.push('')
    return row.map((c) => c.trim().replace(/\|/g, '\\|'))
  })
  const line = (cells: string[]) => `| ${cells.join(' | ')} |`
  return [
    line(norm[0]),
    `| ${norm[0].map(() => '---').join(' | ')} |`,
    ...norm.slice(1).map(line),
  ].join('\n')
}
