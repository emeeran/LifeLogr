import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MoodBars from './MoodBars.vue'

describe('MoodBars', () => {
  it('renders known moods in scale order (awful→great) regardless of input order', () => {
    const wrapper = mount(MoodBars, {
      props: { moods: [{ mood: 'good', count: 10 }, { mood: 'awful', count: 2 }] },
    })
    const labels = wrapper.findAll('span').map((s) => s.text())
    expect(labels.indexOf('awful')).toBeLessThan(labels.indexOf('good'))
    expect(wrapper.text()).toContain('10')
    expect(wrapper.text()).toContain('2')
  })

  it('appends unknown mood labels after the known scale', () => {
    const wrapper = mount(MoodBars, {
      props: {
        moods: [
          { mood: 'zen', count: 4 },
          { mood: 'meh', count: 1 },
        ],
      },
    })
    const labels = wrapper.findAll('span').map((s) => s.text())
    expect(labels.indexOf('meh')).toBeLessThan(labels.indexOf('zen'))
  })

  it('scales bar widths against the largest count', () => {
    const wrapper = mount(MoodBars, {
      props: { moods: [{ mood: 'great', count: 8 }, { mood: 'bad', count: 2 }] },
    })
    const tracks = wrapper.findAll('.relative.h-3\\.5 > div')
    expect(tracks.length).toBe(2)
    // Rows render in scale order: bad (index 1) before great (index 4).
    expect(tracks[0].attributes('style')).toContain('width: 25%')
    expect(tracks[1].attributes('style')).toContain('width: 100%')
  })

  it('exposes an sr-only table twin', () => {
    const wrapper = mount(MoodBars, {
      props: { moods: [{ mood: 'good', count: 1 }] },
    })
    expect(wrapper.find('table.sr-only').exists()).toBe(true)
  })
})
