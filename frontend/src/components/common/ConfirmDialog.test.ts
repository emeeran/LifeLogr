import { describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import ConfirmDialog from './ConfirmDialog.vue'

/**
 * ConfirmDialog — the app's destructive-action gate (delete note / page /
 * notebook all funnel through `confirm()`-style prompts). Self-contained: two
 * props, two emits, an Escape listener on `document`, and a click-away on the
 * backdrop. Nothing to mock.
 */

function mountDialog() {
  return mount(ConfirmDialog, {
    props: {
      title: 'Delete note',
      message: 'This can be restored later.',
    },
  })
}

function buttons(wrapper: VueWrapper) {
  const cancel = wrapper.findAll('button').find((b) => b.text() === 'Cancel')
  const confirm = wrapper.findAll('button').find((b) => b.text() === 'Confirm')
  if (!cancel || !confirm) throw new Error('dialog buttons missing')
  return { cancel, confirm }
}

describe('ConfirmDialog', () => {
  it('renders the title and message', () => {
    const wrapper = mountDialog()
    expect(wrapper.get('h3').text()).toBe('Delete note')
    expect(wrapper.get('p').text()).toBe('This can be restored later.')
    wrapper.unmount()
  })

  it('emits confirm from the Confirm button', async () => {
    const wrapper = mountDialog()
    await buttons(wrapper).confirm.trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toBeUndefined()
    wrapper.unmount()
  })

  it('emits cancel from the Cancel button', async () => {
    const wrapper = mountDialog()
    await buttons(wrapper).cancel.trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()
    wrapper.unmount()
  })

  it('emits cancel on a backdrop click but not on a click inside the card', async () => {
    const wrapper = mountDialog()
    const backdrop = wrapper.get('.fixed.inset-0')
    await backdrop.trigger('click') // click lands on the overlay itself
    expect(wrapper.emitted('cancel')).toHaveLength(1)

    // A click on the card body (e.g. selecting text) must not dismiss.
    await wrapper.get('h3').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })

  it('emits cancel on Escape via a document-level listener', () => {
    const wrapper = mountDialog()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })

  it('stops listening for Escape after unmount', () => {
    const wrapper = mountDialog()
    wrapper.unmount()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('cancel')).toBeUndefined()
  })

  it('keeps working with arbitrary copy (no hardcoded strings)', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { title: 'Reset database', message: 'All entries are gone.' },
    })
    expect(wrapper.get('h3').text()).toBe('Reset database')
    expect(wrapper.get('p').text()).toBe('All entries are gone.')
    wrapper.unmount()
  })
})
