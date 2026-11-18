import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import VideoThumb from './VideoThumb.vue'

/**
 * LW-6.2 — a video tile must not mount a decoding <video> element until it
 * nears the viewport. happy-dom has no IntersectionObserver, so the suite
 * stubs one whose instances can be driven manually.
 */

let observers: FakeIntersectionObserver[] = []

class FakeIntersectionObserver {
  static callback: IntersectionObserverCallback | null = null
  observed: Element[] = []
  cb: IntersectionObserverCallback
  options?: IntersectionObserverInit
  constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.cb = cb
    this.options = options
    observers.push(this)
    FakeIntersectionObserver.callback = cb
  }
  observe(el: Element) {
    this.observed.push(el)
  }
  unobserve(el: Element) {
    this.observed = this.observed.filter((x) => x !== el)
  }
  disconnect() {
    this.observed = []
  }
  /** Test helper: report every observed element as in-viewport. */
  fireAll() {
    this.cb(
      this.observed.map(
        (target) =>
          ({ target, isIntersecting: true }) as IntersectionObserverEntry,
      ),
      this as unknown as IntersectionObserver,
    )
  }
}

beforeEach(() => {
  observers = []
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as never)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VideoThumb', () => {
  it('renders a static placeholder (no video element) before it is in view', async () => {
    const wrapper = mount(VideoThumb, { props: { src: '/media/5/file' } })
    // useIntersectionObserver observes in a post-flush watcher.
    await wrapper.vm.$nextTick()
    expect(wrapper.find('video').exists()).toBe(false)
    expect(observers).toHaveLength(1)
    expect(observers[0].options?.rootMargin).toBe('300px')
    expect(observers[0].observed).toHaveLength(1)
    wrapper.unmount()
  })

  it('mounts the muted first-frame video once the observer reports visibility', async () => {
    const wrapper = mount(VideoThumb, { props: { src: '/media/5/file' } })
    await wrapper.vm.$nextTick()
    observers[0].fireAll()
    await wrapper.vm.$nextTick()
    const video = wrapper.find('video')
    expect(video.exists()).toBe(true)
    expect(video.attributes('src')).toBe('/media/5/file')
    expect(video.attributes('muted')).toBeDefined()
    expect(video.attributes('preload')).toBe('metadata')
    wrapper.unmount()
  })

  it('stays a placeholder while the observer reports nothing', async () => {
    const wrapper = mount(VideoThumb, { props: { src: '/media/5/file' } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
    wrapper.unmount()
  })
})
