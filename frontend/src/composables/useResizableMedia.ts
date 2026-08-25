/**
 * useResizableMedia — wrap preview-rendered <img>/<video> elements in
 * drag-resizable spans, persisting the chosen size per src.
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

export function useResizableMedia(storageKey: string) {
  const mediaSizes = useLocalStorage<MediaSizes>(storageKey, {})
  let observers: ResizeObserver[] = []

  function disconnect() {
    observers.forEach((o) => o.disconnect())
    observers = []
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

  return { mediaSizes: mediaSizes as RemovableRef<MediaSizes>, wrapResizableMedia, disconnect }
}
