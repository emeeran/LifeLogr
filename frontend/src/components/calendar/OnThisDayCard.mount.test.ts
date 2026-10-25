import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

/**
 * OnThisDayCard — groups prior-year entries by year (newest first) and emits
 * openEntry on click; renders nothing when there are no memories.
 */

const NOW = new Date()
const THIS_YEAR = NOW.getFullYear()

function iso(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function todayIso(): string {
  return iso(THIS_YEAR, NOW.getMonth() + 1, NOW.getDate())
}

async function mountCard(entries: unknown[]) {
  const { default: OnThisDayCard } = await import('./OnThisDayCard.vue')
  return mount(OnThisDayCard, {
    props: { entries: entries as never, today: todayIso() },
  })
}

describe('OnThisDayCard', () => {
  it('renders nothing without entries', async () => {
    const wrapper = await mountCard([])
    expect(wrapper.findComponent({ name: 'OnThisDayCard' }).exists()).toBe(true)
    expect(wrapper.text()).not.toContain('On this day')
  })

  it('groups entries by year, newest first, with a years-ago label', async () => {
    const wrapper = await mountCard([
      { id: 1, entry_date: iso(THIS_YEAR - 3, NOW.getMonth() + 1, NOW.getDate()), title: 'Three back', mood: null, is_encrypted: false, tags: [] },
      { id: 2, entry_date: iso(THIS_YEAR - 1, NOW.getMonth() + 1, NOW.getDate()), title: 'Last year', mood: 'good', is_encrypted: false, tags: [] },
      { id: 3, entry_date: iso(THIS_YEAR - 1, NOW.getMonth() + 1, NOW.getDate()), title: 'Same day too', mood: null, is_encrypted: false, tags: [] },
    ])
    const text = wrapper.text()
    expect(text).toContain('On this day')
    expect(text).toContain('1 year ago')
    expect(text).toContain('3 years ago')
    expect(text).toContain('Last year')
    // Newest year's chips come before older ones.
    const lastIndex = text.indexOf('Last year')
    const threeIndex = text.indexOf('Three back')
    expect(lastIndex).toBeGreaterThan(-1)
    expect(threeIndex).toBeGreaterThan(lastIndex)
  })

  it('falls back to a placeholder label for untitled and encrypted entries', async () => {
    const wrapper = await mountCard([
      { id: 4, entry_date: iso(THIS_YEAR - 2, NOW.getMonth() + 1, NOW.getDate()), title: null, mood: null, is_encrypted: false, tags: [] },
      { id: 5, entry_date: iso(THIS_YEAR - 2, NOW.getMonth() + 1, NOW.getDate()), title: null, mood: null, is_encrypted: true, tags: [] },
    ])
    expect(wrapper.text()).toContain('Journal entry')
    expect(wrapper.text()).toContain('Encrypted')
  })

  it('emits openEntry with the entry id on click', async () => {
    const wrapper = await mountCard([
      { id: 9, entry_date: iso(THIS_YEAR - 1, NOW.getMonth() + 1, NOW.getDate()), title: 'Clickable', mood: null, is_encrypted: false, tags: [] },
    ])
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('openEntry')).toEqual([[9]])
  })
})
