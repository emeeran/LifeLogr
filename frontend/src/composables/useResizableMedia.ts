/**
 * useResizableMedia — wrap preview-rendered <img>/<video> elements in
 * drag-resizable spans, persisting the chosen size per src, and (optionally)
 * attach a hover "OCR" pill to each image.
 *
 * The markdown body stays untouched (sizes live in localStorage keyed by the
 * media URL, which is unique per upload); this only manipulates the rendered
 * preview. Re-run `wrapResizableMedia` after every preview re-render.
 *
 * Shared by the journal (EntryEditor) and notes (NoteEditor) editors.
 */
import { useLocalStorage, type RemovableRef } from '@vueuse/core'
import { onUnmounted } from 'vue'

export interface MediaSizes {
  [src: string]: { w: number; h: number }
}

export interface ResizableMediaOptions {
  storageKey: string
  /** Show the hover OCR pill on images (editors with an OCR flow). */
  ocrButton?: boolean
  /** Called with the image's src when its OCR pill is clicked. */
  onOcr?: (src: string, mediaEl: HTMLImageElement) => void
  /** Double-click an <img>/<video> in the preview (e.g. open the viewer). */
  onMediaDblClick?: (el: HTMLImageElement | HTMLVideoElement) => void
}

export function useResizableMedia(opts: ResizableMediaOptions) {
  const { storageKey, ocrButton = false, onOcr, onMediaDblClick } = opts
  const mediaSizes = useLocalStorage<MediaSizes>(storageKey, {})
  let observers: ResizeObserver[] = []

  function disconnect() {
    observers.forEach((o) => o.disconnect())
    observers = []
  }

  /** Delegated click handler for the OCR pills — bind once on the preview
   *  container; pills are re-created on every re-render so per-element
   *  listeners wouldn't survive. */
  function onPreviewClick(e: MouseEvent) {
    if (!onOcr) return
    const btn = (e.target as HTMLElement).closest('.ocr-btn')
    if (!btn) return
    e.preventDefault()
    const wrap = btn.closest('.rmedia') as HTMLElement | null
    const img = wrap?.querySelector('img')
    const src = img?.getAttribute('src') || ''
    if (src) onOcr(src, img as HTMLImageElement)
  }

  /** Delegated double-click: opens the media in the full-screen viewer
   *  (zoom/resize there). Bind on the preview container. */
  function onPreviewDblClick(e: MouseEvent) {
    if (!onMediaDblClick) return
    const media = (e.target as HTMLElement).closest<HTMLElement>('.rmedia img, .rmedia video')
    if (media) onMediaDblClick(media as HTMLImageElement | HTMLVideoElement)
  }

  function wrapResizableMedia(root: HTMLElement | null) {
    disconnect()
    if (!root) return
    root.querySelectorAll('img, video').forEach((node) => {
      const media = node as HTMLImageElement | HTMLVideoElement
      const parent = media.parentElement
      if (!parent) return
      const src = media.getAttribute('src') || ''
      const wrap = document.createElement('span')
      wrap.className = 'rmedia'
      parent.insertBefore(wrap, media)
      wrap.appendChild(media)
      media.style.width = '100%'
      media.style.height = '100%'
      media.style.display = 'block'
      const stored = mediaSizes.value[src]
      if (stored && stored.w) {
        wrap.style.width = stored.w + 'px'
        wrap.style.height = stored.h + 'px'
      }
      if (ocrButton && media.tagName === 'IMG' && !wrap.querySelector('.ocr-btn')) {
        const btn = document.createElement('button')
        btn.className = 'ocr-btn'
        btn.textContent = 'OCR'
        btn.title = 'Extract text from this image (inserted below it)'
        wrap.appendChild(btn)
      }
      const ro = new ResizeObserver((entries) => {
        for (const e of entries) {
          const cr = e.contentRect
          if (cr.width > 40 && cr.height > 40) {
            mediaSizes.value = {
              ...mediaSizes.value,
              [src]: { w: Math.round(cr.width), h: Math.round(cr.height) },
            }
          }
        }
      })
      ro.observe(wrap)
      observers.push(ro)
    })
  }

  onUnmounted(disconnect)

  return {
    mediaSizes: mediaSizes as RemovableRef<MediaSizes>,
    wrapResizableMedia,
    onPreviewClick,
    onPreviewDblClick,
    disconnect,
  }
}
