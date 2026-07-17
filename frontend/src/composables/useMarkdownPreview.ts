import { ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.use({ gfm: true, breaks: true })

/**
 * Composable for rendering a markdown preview of the entry body.
 *
 * Accepts an ``active`` getter — when it returns ``false`` (e.g. preview pane
 * is closed), rendering is **skipped entirely**. This avoids running
 * ``marked`` + ``DOMPurify`` on every debounced keystroke when the user isn't
 * even looking at the preview, which is wasteful for long entries.
 */
export function useMarkdownPreview(
  body: () => string,
  active: () => boolean = () => true,
  debounceMs = 300,
) {
  const renderedPreview = ref('')

  let timer: ReturnType<typeof setTimeout> | null = null

  function render() {
    if (!active()) return // Skip when preview isn't visible
    let html = marked(body()) as string
    html = html.replace(/&lt;!--ENC\{([^}]+)\}--&gt;/g, (_, enc) => {
      return `<span class="enc-block cursor-pointer bg-accent/10 text-accent px-1.5 py-0.5 rounded border border-accent/20 text-[11px] font-medium" data-enc="${enc}">🔒 Decrypt selection</span>`
    })
    html = html.replace(/<!--ENC\{([^}]+)\}-->/g, (_, enc) => {
      return `<span class="enc-block cursor-pointer bg-accent/10 text-accent px-1.5 py-0.5 rounded border border-accent/20 text-[11px] font-medium" data-enc="${enc}">🔒 Decrypt selection</span>`
    })
    renderedPreview.value = DOMPurify.sanitize(html, { ADD_ATTR: ['data-enc'] })
  }

  watch(body, () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(render, debounceMs)
  }, { immediate: true })

  // Re-render immediately when the preview pane opens so the user doesn't
  // see stale content from the last time it was visible.
  watch(active, (now) => {
    if (now) {
      if (timer) clearTimeout(timer)
      render()
    }
  })

  return { renderedPreview }
}
