import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WeeklyBars from './WeeklyBars.vue'
import type { WeeklyCount } from '../../types'

function weeks(counts: number[]): WeeklyCount[] {
  return counts.map((count, i) => ({ week_start: `2026-08-0${i + 1}`, count }))
}

describe('WeeklyBars', () => {
  it('renders one column per non-zero week and y-axis ticks', () => {
    const wrapper = mount(WeeklyBars, {
      props: { data: weeks([0, 2, 0, 5]) },
    })
    const paths = wrapper.findAll('path')
    expect(paths.length).toBe(2) // only non-zero weeks draw a column
    const text = wrapper.text()
    expect(text).toContain('0')
    expect(text).toContain('5')
  })

  it('renders a zero-data chart without columns but with a baseline', () => {
    const wrapper = mount(WeeklyBars, {
      props: { data: weeks([0, 0, 0, 0]) },
    })
    expect(wrapper.findAll('path').length).toBe(0)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('shows a tooltip on column hover', async () => {
    const wrapper = mount(WeeklyBars, {
      props: { data: weeks([1, 0, 0, 0]) },
    })
    await wrapper.find('rect').trigger('mouseenter')
    expect(wrapper.text()).toContain('1 entry')
    await wrapper.find('rect').trigger('mouseleave')
    expect(wrapper.text()).not.toContain('1 entry')
  })

  it('exposes an sr-only table twin', () => {
    const wrapper = mount(WeeklyBars, {
      props: { data: weeks([3]) },
    })
    expect(wrapper.find('table.sr-only').exists()).toBe(true)
    expect(wrapper.text()).toContain('Week starting')
  })
})
