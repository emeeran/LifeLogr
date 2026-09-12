/**
 * useResizableMedia — wrap preview-rendered <img>/<video> elements in
 * drag-resizable spans, persisting the chosen size per src, and (optionally)
 * attach a hover "OCR" pill to each image.
 *
 * Size source of truth is the `?w=<px>&h=<px>` encoded on the media URL in
 * the markdown body (see utils/markdownMedia): the editor persists a settled
 * drag via `onResize` by rewriting the URL, and the next preview render sizes
 * the span from it. The localStorage map is a legacy fallback (sizes saved
 * before body persistence existed) and a drag write-through cache; a legacy
 * entry is dropped once the URL encodes a size. Only genuine user drags write
 * anything — the ResizeObserver's initial callback, pane-clamp refows and
 * post-write re-renders must never bake unintended sizes into the body.
 *
 * Re-run `wrapResizableMedia` after every preview re-render.
 *
 * Shared by the journal (EntryEditor) and notes (NoteEditor) editors.
 */
import { useLocalStorage, type RemovableRef } from '@vueuse/core'
import { onUnmounted } from 'vue'

import { getMediaSize } from '../utils/markdownMedia'

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
  /** A drag settled at a size differing from the `?w=&h=` encoded in src —
   *  the editor persists it into the markdown body. */
  onResize?: (src: string, w: number, h: number) => void
}

/** Quiet period after the last drag event before the drag counts as over. */
const DRAG_IDLE_MS = 500
/** Quiet period after the last RO tick before the size is persisted. */
const SETTLE_MS = 400
const MIN_SIZE = 40
/** Sizes within this of the encoded value count as "already persisted". */
const EPSILON = 1

export function useResizableMedia(opts: ResizableMediaOptions) {
  const {
    storageKey,
    ocrButton = false,
    onOcr,
    onMediaDblClick,
    onResize,
  } = opts
  const mediaSizes = useLocalStorage<MediaSizes>(storageKey, {})
  let observers: ResizeObserver[] = []
  let controllers: AbortController[] = []
  let dragTimers: ReturnType<typeof setTimeout>[] = []
  const settleTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const armed = new Map<string, { w: number; h: number }>()

  function disconnect() {
    observers.forEach((o) => o.disconnect())
    observers = []
    controllers.forEach((c) => c.abort())
    controllers = []
    dragTimers.forEach((t) => clearTimeout(t))
    dragTimers = []
    settleTimers.forEach((t) => clearTimeout(t))
    settleTimers.clear()
    armed.clear()
  }

  /** Persist `src`'s last observed size once the drag has settled — unless it
   *  already matches the size encoded in the URL (i.e. the body write from
   *  the previous round-trip came back to us: stop, no loop). */
  function armSettle(src: string, w: number, h: number) {
    armed.set(src, { w, h })
    const prev = settleTimers.get(src)
    if (prev) clearTimeout(prev)
    const t = setTimeout(() => {
      settleTimers.delete(src)
      const size = armed.get(src)
      armed.delete(src)
      if (!size) return
      const enc = getMediaSize(src)
      if (
        enc &&
        Math.abs(enc.w - size.w) <= EPSILON &&
        Math.abs(enc.h - size.h) <= EPSILON
      )
        return
      onResize?.(src, size.w, size.h)
    }, SETTLE_MS)
    settleTimers.set(src, t)
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
    const media = (e.target as HTMLElement).closest<HTMLElement>(
      '.rmedia img, .rmedia video',
    )
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
      // Body-encoded size wins; a superseded legacy localStorage entry is
      // dropped so the two can't disagree.
      const encoded = getMediaSize(src)
      const legacy = mediaSizes.value[src]
      if (encoded) {
        wrap.style.width = encoded.w + 'px'
        wrap.style.height = encoded.h + 'px'
        if (legacy) {
          const { [src]: _superseded, ...rest } = mediaSizes.value
          mediaSizes.value = rest
        }
      } else if (legacy && legacy.w) {
        wrap.style.width = legacy.w + 'px'
        wrap.style.height = legacy.h + 'px'
      }
      if (
        ocrButton &&
        media.tagName === 'IMG' &&
        !wrap.querySelector('.ocr-btn')
      ) {
        const btn = document.createElement('button')
        btn.className = 'ocr-btn'
        btn.textContent = 'OCR'
        btn.title = 'Extract text from this image (inserted below it)'
        wrap.appendChild(btn)
      }
      // Only a genuine user drag may write a size. pointerdown on the wrap
      // opens the window; it stays open while pointer events keep arriving
      // (the cursor rides the media during a CSS-resize drag) and closes
      // DRAG_IDLE_MS after the last one. The initial-observe callback, pane
      // clamps and reflow re-renders all arrive outside that window.
      let dragging = false
      const armIdle = () => {
        const t = setTimeout(() => {
          dragging = false
          dragTimers = dragTimers.filter((x) => x !== t)
        }, DRAG_IDLE_MS)
        dragTimers.push(t)
      }
      const clearIdle = () => {
        dragTimers.forEach((t) => clearTimeout(t))
        dragTimers = []
      }
      const ctl = new AbortController()
      controllers.push(ctl)
      const opts = { signal: ctl.signal, capture: true } as const
      wrap.addEventListener(
        'pointerdown',
        () => {
          clearIdle()
          dragging = true
          armIdle()
        },
        { signal: ctl.signal },
      )
      window.addEventListener(
        'pointermove',
        () => {
          if (dragging) {
            clearIdle()
            dragging = true
            armIdle()
          }
        },
        opts,
      )
      window.addEventListener('pointerup', () => {
        if (dragging) {
          clearIdle()
          armIdle()
        }
      }, opts)
      const ro = new ResizeObserver(() => {
        if (!dragging) return
        // Border box: matches the CSS size the `resize: both` handle writes
        // and the value we apply — contentRect would read 2px small (the
        // wrap's border) and shrink-loop across re-renders.
        const r = wrap.getBoundingClientRect()
        const w = Math.round(r.width)
        const h = Math.round(r.height)
        if (w <= MIN_SIZE || h <= MIN_SIZE) return
        mediaSizes.value = { ...mediaSizes.value, [src]: { w, h } }
        armSettle(src, w, h)
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
