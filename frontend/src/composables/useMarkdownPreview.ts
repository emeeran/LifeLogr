import { ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.use({ gfm: true, breaks: true })

export function useMarkdownPreview(body: () => string, debounceMs = 300) {
  const renderedPreview = ref('')

  let timer: ReturnType<typeof setTimeout> | null = null

  function render() {
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

  return { renderedPreview }
}
