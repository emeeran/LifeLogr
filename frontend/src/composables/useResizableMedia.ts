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
  /** Render at most this many inline media at once, with a "Show N more"
   *  control. Bounds decode memory on long, media-heavy entries. */
  maxInline?: number
}

/** Quiet period after the last drag event before the drag counts as over. */
const DRAG_IDLE_MS = 500
/** Quiet period after the last RO tick before the size is persisted. */
const SETTLE_MS = 400
const MIN_SIZE = 40
/** Sizes within this of the encoded value count as "already persisted". */
const EPSILON = 1
/** Minimum interval between localStorage writes while a drag is in flight. */
const RESIZE_WRITE_MS = 300

export function useResizableMedia(opts: ResizableMediaOptions) {
  const {
    storageKey,
    ocrButton = false,
    onOcr,
    onMediaDblClick,
    onResize,
    maxInline,
  } = opts
  const mediaSizes = useLocalStorage<MediaSizes>(storageKey, {})
  let observers: ResizeObserver[] = []
  let controllers: AbortController[] = []
  let dragTimers: ReturnType<typeof setTimeout>[] = []
  const settleTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const armed = new Map<string, { w: number; h: number }>()
  // Resize ticks arrive per-frame; writing the whole size map to localStorage
  // on each one used to serialize a JSON blob dozens of times per second.
  // Ticks accumulate here and flush at most once per RESIZE_WRITE_MS, plus once
  // more when the drag settles.
  const pendingWrites = new Map<string, { w: number; h: number }>()
  let lastWrite = 0
  let writeTimer: ReturnType<typeof setTimeout> | null = null

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
    if (writeTimer) {
      clearTimeout(writeTimer)
      writeTimer = null
    }
  }

  /** Write every pending size into localStorage once. */
  function flushSizes() {
    lastWrite = Date.now()
    if (writeTimer) {
      clearTimeout(writeTimer)
      writeTimer = null
    }
    if (!pendingWrites.size) return
    const next = { ...mediaSizes.value }
    pendingWrites.forEach((v, k) => (next[k] = v))
    pendingWrites.clear()
    mediaSizes.value = next
  }

  /** Record a drag tick, writing at most once per RESIZE_WRITE_MS (the last
   *  tick of a burst is always flushed by the trailing timer). */
  function recordSize(src: string, w: number, h: number) {
    pendingWrites.set(src, { w, h })
    const elapsed = Date.now() - lastWrite
    if (elapsed >= RESIZE_WRITE_MS) {
      flushSizes()
      return
    }
    if (writeTimer) return
    writeTimer = setTimeout(
      () => {
        writeTimer = null
        flushSizes()
      },
      RESIZE_WRITE_MS - elapsed,
    )
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
      flushSizes()
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
      // One AbortController for every listener on this wrapper (OCR is a real
      // child node, so it needs none). Declared before the grip handlers.
      const ctl = new AbortController()
      controllers.push(ctl)
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

      // Explicit grip. WebKit draws no affordance for a CSS `resize: both`
      // element, so the corner is invisible until someone guesses it is there.
      // This handle is visible on hover/focus, drives the same settle path,
      // and adds a keyboard equivalent. The native CSS corner still works.
      const grip = document.createElement('span')
      grip.className = 'rmedia-grip'
      grip.tabIndex = 0
      grip.setAttribute('role', 'separator')
      grip.setAttribute('aria-label', 'Resize media')
      grip.title = 'Drag to resize (focus + arrow keys)'
      wrap.appendChild(grip)
      const badge = document.createElement('span')
      badge.className = 'rmedia-size'
      const encodedForBadge = getMediaSize(src)
      if (encodedForBadge) {
        badge.textContent = `${encodedForBadge.w} × ${encodedForBadge.h}`
      }
      wrap.appendChild(badge)

      let gripDrag: { x: number; y: number; w: number; h: number } | null =
        null
      const resizeTo = (w: number, h: number) => {
        wrap.style.width = `${w}px`
        wrap.style.height = `${h}px`
        badge.textContent = `${w} × ${h}`
        recordSize(src, w, h)
        armSettle(src, w, h)
      }
      grip.addEventListener(
        'pointerdown',
        (e: PointerEvent) => {
          e.preventDefault()
          // Keep the wrapper's own drag-window handler from arming the RO path
          // for this gesture — the grip writes sizes directly.
          e.stopPropagation()
          const r = wrap.getBoundingClientRect()
          gripDrag = {
            x: e.clientX,
            y: e.clientY,
            w: Math.round(r.width),
            h: Math.round(r.height),
          }
          wrap.classList.add('rmedia-active')
          try {
            grip.setPointerCapture(e.pointerId)
          } catch {
            /* jsdom / older engines */
          }
        },
        { signal: ctl.signal },
      )
      grip.addEventListener(
        'pointermove',
        (e: PointerEvent) => {
          if (!gripDrag) return
          e.preventDefault()
          const w = Math.max(
            MIN_SIZE,
            Math.round(gripDrag.w + e.clientX - gripDrag.x),
          )
          const h = Math.max(
            MIN_SIZE,
            Math.round(gripDrag.h + e.clientY - gripDrag.y),
          )
          wrap.style.width = `${w}px`
          wrap.style.height = `${h}px`
          badge.textContent = `${w} × ${h}`
          recordSize(src, w, h)
          armSettle(src, w, h)
        },
        { signal: ctl.signal },
      )
      const endGrip = (e: PointerEvent) => {
        if (!gripDrag) return
        gripDrag = null
        wrap.classList.remove('rmedia-active')
        try {
          grip.releasePointerCapture(e.pointerId)
        } catch {
          /* jsdom / older engines */
        }
        const r = wrap.getBoundingClientRect()
        resizeTo(Math.round(r.width), Math.round(r.height))
      }
      grip.addEventListener('pointerup', endGrip, { signal: ctl.signal })
      grip.addEventListener('pointercancel', endGrip, { signal: ctl.signal })
      grip.addEventListener(
        'keydown',
        (e: KeyboardEvent) => {
          const step = e.shiftKey ? 40 : 10
          const r = wrap.getBoundingClientRect()
          let w = Math.round(r.width)
          let h = Math.round(r.height)
          if (e.key === 'ArrowLeft') w = Math.max(MIN_SIZE, w - step)
          else if (e.key === 'ArrowRight') w += step
          else if (e.key === 'ArrowUp') h = Math.max(MIN_SIZE, h - step)
          else if (e.key === 'ArrowDown') h += step
          else return
          e.preventDefault()
          e.stopPropagation()
          resizeTo(w, h)
        },
        { signal: ctl.signal },
      )
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
      // Native CSS-corner fallback: pointerdown on the wrap opens a window in
      // which ResizeObserver ticks count as a user drag (and are persisted).
      // The grip path above sets its own sizes and never needs this window.
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
      window.addEventListener(
        'pointerup',
        () => {
          if (dragging) {
            clearIdle()
            armIdle()
          }
        },
        opts,
      )
      const ro = new ResizeObserver(() => {
        if (!dragging) return
        // Border box: matches the CSS size the `resize: both` handle writes
        // and the value we apply — contentRect would read 2px small (the
        // wrap's border) and shrink-loop across re-renders.
        const r = wrap.getBoundingClientRect()
        const w = Math.round(r.width)
        const h = Math.round(r.height)
        if (w <= MIN_SIZE || h <= MIN_SIZE) return
        recordSize(src, w, h)
        armSettle(src, w, h)
      })
      ro.observe(wrap)
      observers.push(ro)
    })

    if (maxInline && maxInline > 0) {
      capInlineMedia(root, maxInline)
    }
  }

  /** Hide media past *limit* and offer a one-click reveal for this render. */
  function capInlineMedia(root: HTMLElement, limit: number) {
    root.querySelector('.rmedia-more')?.remove()
    const wraps = Array.from(root.querySelectorAll<HTMLElement>('.rmedia'))
    wraps.forEach((wrap, index) => {
      wrap.style.display = index < limit ? '' : 'none'
    })
    const hidden = wraps.length - limit
    if (hidden <= 0) return

    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'rmedia-more'
    button.textContent = `Show ${hidden} more`
    button.addEventListener('click', () => {
      wraps.forEach((wrap) => (wrap.style.display = ''))
      button.remove()
    })
    const anchor = wraps[limit - 1]
    anchor.parentElement?.insertBefore(button, anchor.nextSibling)
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
