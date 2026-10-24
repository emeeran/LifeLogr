import { ref, watch } from 'vue'
import { renderMarkdown } from '../utils/markdown'

/**
 * Composable for rendering a markdown preview of the entry body.
 *
 * Accepts an ``active`` getter — when it returns ``false`` (e.g. preview pane
 * is closed), rendering is **skipped entirely**. This avoids running
 * ``marked`` + ``DOMPurify`` on every debounced keystroke when the user isn't
 * even looking at the preview, which is wasteful for long entries.
 *
 * The marked/DOMPurify setup itself lives in utils/markdown (shared with the
 * entry detail, scribble pad and changelog renders).
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
    renderedPreview.value = renderMarkdown(body())
  }

  watch(
    body,
    () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(render, debounceMs)
    },
    { immediate: true },
  )

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
