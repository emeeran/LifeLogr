import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MediaViewer from './MediaViewer.vue'
import { API_ORIGIN } from '../../api/client'
import type { MediaResponse } from '../../types'

/**
 * LW-6.1 — the viewer decodes the cached ≤640px /thumb while the display is
 * within ~2× the viewport and only swaps to the full /file original once the
 * user zooms past that; download always points at the full original.
 */

const item: MediaResponse = {
  id: 7,
  entry_id: 1,
  filename: 'photo.jpg',
  media_type: 'image',
  file_size: 2048,
  caption: null,
  created_at: '',
}

function mountViewer() {
  return mount(MediaViewer, {
    props: { items: [item], index: 0 },
    attachTo: document.body,
  })
}

describe('MediaViewer thumbnail-first display', () => {
  it('renders a fit-to-screen image from the thumb endpoint', () => {
    const wrapper = mountViewer()
    const img = wrapper.find('img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe(`${API_ORIGIN}/api/v1/media/7/thumb`)
    wrapper.unmount()
  })

  it('keeps the download link on the full original', () => {
    const wrapper = mountViewer()
    const download = wrapper.find('a[aria-label="Download"]')
    expect(download.exists()).toBe(true)
    expect(download.attributes('href')).toBe(
      `${API_ORIGIN}/api/v1/media/7/file`,
    )
    wrapper.unmount()
  })

  it('swaps to the full original once zoom passes ~2× viewport', async () => {
    const wrapper = mountViewer()
    const zoomIn = wrapper.find('button[aria-label="Zoom in"]')
    expect(zoomIn.exists()).toBe(true)
    // zoom steps 0.25 from 1; 1.75 still uses the thumb, 2.25 does not.
    for (let i = 0; i < 3; i += 1) await zoomIn.trigger('click')
    expect(wrapper.find('img').attributes('src')).toBe(
      `${API_ORIGIN}/api/v1/media/7/thumb`,
    )
    for (let i = 0; i < 2; i += 1) await zoomIn.trigger('click')
    expect(wrapper.find('img').attributes('src')).toBe(
      `${API_ORIGIN}/api/v1/media/7/file`,
    )
    // Zooming back out to fit returns to the cheap decode.
    const reset = wrapper.find('button[aria-label="Reset zoom"]')
    await reset.trigger('click')
    expect(wrapper.find('img').attributes('src')).toBe(
      `${API_ORIGIN}/api/v1/media/7/thumb`,
    )
    wrapper.unmount()
  })

  it('always streams the full file for video (no thumb endpoint)', () => {
    const wrapper = mount(MediaViewer, {
      props: {
        items: [{ ...item, id: 9, media_type: 'video', filename: 'clip.mp4' }],
        index: 0,
      },
      attachTo: document.body,
    })
    const video = wrapper.find('video')
    expect(video.exists()).toBe(true)
    expect(video.attributes('src')).toBe(`${API_ORIGIN}/api/v1/media/9/file`)
    wrapper.unmount()
  })
})
