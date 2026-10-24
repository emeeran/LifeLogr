import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ToasterHost from './ToasterHost.vue'
import { useToastStore } from '../../stores/toast'

/**
 * ToasterHost — the single app-wide surface for failures and confirmations
 * (mounted once in App.vue, fed by the toast store). This pins the
 * store → DOM contract: one node per toast, the right severity styling, a
 * live-region announcement for screen readers, and a working dismiss button.
 */

async function mountHost() {
  // One pinia shared by the component AND the test's `useToastStore()` handle
  // — separate instances would silently talk past each other. TransitionGroup
  // is un-stubbed so the toasts are real DOM under [role="status"].
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ToasterHost, {
    global: { plugins: [pinia], stubs: { 'transition-group': false } },
  })
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

/**
 * jsdom never fires `transitionend`, and fake timers freeze the frame that
 * resolves a TransitionGroup leave — so a dismissed toast lingers in the DOM
 * until we advance past the 0.3s transition ourselves.
 */
async function flushLeave(wrapper: Awaited<ReturnType<typeof mountHost>>) {
  await wrapper.vm.$nextTick() // let the removal render and the leave begin
  vi.advanceTimersByTime(500) // run the frame that resolves the leave
  await wrapper.vm.$nextTick()
}

describe('ToasterHost', () => {
  it('renders nothing when the queue is empty', async () => {
    const wrapper = await mountHost()
    expect(wrapper.findAll('[role="status"] > *')).toHaveLength(0)
    expect(wrapper.text()).toBe('')
    wrapper.unmount()
  })

  it('renders one node per pushed toast with its message', async () => {
    const wrapper = await mountHost()
    const toast = useToastStore()
    toast.error('Save failed')
    toast.success('Saved')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Save failed')
    expect(wrapper.text()).toContain('Saved')
    expect(wrapper.findAll('button[aria-label="Dismiss notification"]')).toHaveLength(2)
    wrapper.unmount()
  })

  it('announces through a polite live region', async () => {
    const wrapper = await mountHost()
    const region = wrapper.get('[role="status"]')
    expect(region.attributes('aria-live')).toBe('polite')
    wrapper.unmount()
  })

  it('styles each severity distinctly', async () => {
    const wrapper = await mountHost()
    const toast = useToastStore()
    toast.error('bad')
    toast.success('good')
    toast.info('fyi')
    await wrapper.vm.$nextTick()

    const nodes = wrapper.findAll('[role="status"] > *')
    expect(nodes).toHaveLength(3)
    expect(nodes[0].classes().join(' ')).toContain('bg-red-900/90')
    expect(nodes[1].classes().join(' ')).toContain('bg-green-900/90')
    expect(nodes[2].classes().join(' ')).toContain('bg-surface')
    wrapper.unmount()
  })

  it('dismiss button removes only that toast', async () => {
    const wrapper = await mountHost()
    const toast = useToastStore()
    toast.info('first')
    toast.info('second')
    await wrapper.vm.$nextTick()

    await wrapper.findAll('button[aria-label="Dismiss notification"]')[0].trigger('click')
    await flushLeave(wrapper)
    expect(wrapper.text()).not.toContain('first')
    expect(wrapper.text()).toContain('second')
    wrapper.unmount()
  })

  it('drops toasts when their store timer expires', async () => {
    const wrapper = await mountHost()
    const toast = useToastStore()
    toast.info('fleeting', 1000)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('fleeting')

    vi.advanceTimersByTime(1000)
    await flushLeave(wrapper)
    expect(wrapper.text()).not.toContain('fleeting')
    wrapper.unmount()
  })

  it('reflects store.clearAll() immediately', async () => {
    const wrapper = await mountHost()
    const toast = useToastStore()
    toast.error('a')
    toast.error('b')
    await wrapper.vm.$nextTick()
    toast.clearAll()
    await flushLeave(wrapper)
    expect(wrapper.findAll('[role="status"] > *')).toHaveLength(0)
    wrapper.unmount()
  })
})
