import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { useResizableMedia } from './useResizableMedia'

/**
 * The resize *mechanism* predates this suite; these tests pin the explicit
 * grip added because WebKit draws no affordance for a CSS `resize: both`
 * element (the reported "can't resize pasted images" behaviour).
 */

class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const SRC = '/api/v1/media/7/file'
let storageSeq = 0

function setup(
  onResize = vi.fn(),
  opts: { images?: number; maxInline?: number } = {},
) {
  let api: ReturnType<typeof useResizableMedia> | null = null
  const count = opts.images ?? 1
  const Comp = defineComponent({
    setup() {
      api = useResizableMedia({
        storageKey: `test-rmedia-${++storageSeq}`,
        onResize,
        maxInline: opts.maxInline,
      })
      return () => null
    },
  })
  const wrapper = mount(Comp)
  const root = document.createElement('div')
  const images: HTMLImageElement[] = []
  for (let i = 0; i < count; i += 1) {
    const img = document.createElement('img')
    img.setAttribute('src', i === 0 ? SRC : `/api/v1/media/${i + 1}/file`)
    root.appendChild(img)
    images.push(img)
  }
  api!.wrapResizableMedia(root)

  const wrap = root.querySelector('.rmedia') as HTMLElement
  // jsdom has no layout; read the size back from the inline style so the
  // pointer-up commit sees the size the drag just wrote.
  wrap.getBoundingClientRect = () => {
    const width = Number.parseFloat(wrap.style.width || '200')
    const height = Number.parseFloat(wrap.style.height || '150')
    return { width, height, top: 0, left: 0, right: width, bottom: height } as DOMRect
  }
  const grip = root.querySelector('.rmedia-grip') as HTMLElement
  return { api: api!, wrapper, root, img: images[0], images, wrap, grip, onResize }
}

function pointer(el: Element, type: string, x: number, y: number) {
  el.dispatchEvent(
    new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true }),
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useResizableMedia grip', () => {
  it('wraps the image and renders a visible grip + size badge', () => {
    const { img, wrap, grip } = setup()
    expect(img.parentElement).toBe(wrap)
    expect(wrap.className).toContain('rmedia')
    expect(grip.getAttribute('aria-label')).toBe('Resize media')
    expect(grip.tabIndex).toBe(0)
    expect(wrap.querySelector('.rmedia-size')).not.toBeNull()
  })

  it('commits a dragged size through onResize', () => {
    const { onResize, grip, wrap } = setup()

    pointer(grip, 'pointerdown', 0, 0)
    pointer(grip, 'pointermove', 60, 40)
    expect(wrap.style.width).toBe('260px')
    expect(wrap.style.height).toBe('190px')
    pointer(grip, 'pointerup', 60, 40)

    vi.advanceTimersByTime(600)
    expect(onResize).toHaveBeenCalledWith(SRC, 260, 190)
  })

  it('clamps to the minimum size', () => {
    const { onResize, grip, wrap } = setup()

    pointer(grip, 'pointerdown', 200, 150)
    pointer(grip, 'pointermove', 0, 0)
    pointer(grip, 'pointerup', 0, 0)

    vi.advanceTimersByTime(600)
    expect(wrap.style.width).toBe('40px')
    expect(onResize).toHaveBeenCalledWith(SRC, 40, 40)
  })

  it('resizes from the keyboard (Shift = larger step)', () => {
    const { onResize, grip } = setup()

    grip.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }),
    )
    vi.advanceTimersByTime(600)
    expect(onResize).toHaveBeenLastCalledWith(SRC, 210, 150)

    grip.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowDown', shiftKey: true, bubbles: true }),
    )
    vi.advanceTimersByTime(600)
    expect(onResize).toHaveBeenLastCalledWith(SRC, 210, 190)
  })

  it('ignores pointer moves that did not start on the grip', () => {
    const { onResize, grip } = setup()
    pointer(grip, 'pointermove', 80, 80)
    pointer(grip, 'pointerup', 80, 80)
    vi.advanceTimersByTime(600)
    expect(onResize).not.toHaveBeenCalled()
  })

  it('caps inline media and reveals the rest on demand', () => {
    const { root } = setup(vi.fn(), { images: 15, maxInline: 12 })
    const wraps = Array.from(root.querySelectorAll<HTMLElement>('.rmedia'))
    expect(wraps).toHaveLength(15)
    expect(wraps[11].style.display).toBe('')
    expect(wraps[12].style.display).toBe('none')
    expect(wraps[14].style.display).toBe('none')

    const more = root.querySelector('.rmedia-more') as HTMLButtonElement
    expect(more.textContent).toBe('Show 3 more')
    more.click()

    expect(wraps[14].style.display).toBe('')
    expect(root.querySelector('.rmedia-more')).toBeNull()
  })

  it('adds no control when the preview is under the cap', () => {
    const { root } = setup(vi.fn(), { images: 3, maxInline: 12 })
    expect(root.querySelectorAll('.rmedia')).toHaveLength(3)
    expect(root.querySelector('.rmedia-more')).toBeNull()
  })
})
