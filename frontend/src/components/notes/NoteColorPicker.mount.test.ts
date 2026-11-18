import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import NoteColorPicker from './NoteColorPicker.vue'

describe('NoteColorPicker', () => {
  it('renders a neutral trigger when the item has no colour', () => {
    const wrapper = mount(NoteColorPicker, { props: { modelValue: null } })
    expect(wrapper.find('.color-trigger').exists()).toBe(true)
    expect(wrapper.find('.color-dot').exists()).toBe(false)
    expect(wrapper.find('.color-trigger').attributes('aria-label')).toBe(
      'item colour: None',
    )
    wrapper.unmount()
  })

  it('names the current colour in the trigger (colour is not the only cue)', () => {
    const wrapper = mount(NoteColorPicker, {
      props: { modelValue: '#059669', noun: 'notebook' },
    })
    expect(wrapper.find('.color-trigger').attributes('aria-label')).toBe(
      'notebook colour: Emerald',
    )
    expect(wrapper.find('.color-dot').attributes('style')).toContain(
      '#059669',
    )
    wrapper.unmount()
  })

  it('opens the palette, marks the current swatch, and emits a choice', async () => {
    const wrapper = mount(NoteColorPicker, {
      props: { modelValue: '#059669' },
    })
    await wrapper.find('.color-trigger').trigger('click')

    const swatches = wrapper.findAll('.swatch')
    expect(swatches).toHaveLength(8)
    const emerald = swatches.find(
      (s) => s.attributes('aria-label') === 'Emerald',
    )
    expect(emerald?.attributes('aria-checked')).toBe('true')
    expect(wrapper.find('.none').exists()).toBe(true)

    const rose = swatches.find((s) => s.attributes('aria-label') === 'Rose')
    await rose!.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['#e11d48'])
    expect(wrapper.find('.color-popover').exists()).toBe(false)
    wrapper.unmount()
  })

  it('clears the colour with None', async () => {
    const wrapper = mount(NoteColorPicker, {
      props: { modelValue: '#0284c7' },
    })
    await wrapper.find('.color-trigger').trigger('click')
    await wrapper.find('.none').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([null])
    wrapper.unmount()
  })
})
