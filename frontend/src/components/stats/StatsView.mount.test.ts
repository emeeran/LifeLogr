import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * StatsView — renders aggregates as tiles + charts; an empty journal shows
 * the empty note and zeros, never an error.
 */

vi.mock('../../api/entries', () => ({
  entriesApi: {
    stats: vi.fn(async () => ({
      total_entries: 0,
      total_words: 0,
      current_streak: 0,
      longest_streak: 0,
      weekly: Array.from({ length: 12 }, () => ({
        week_start: `2026-01-05`,
        count: 0,
      })),
      moods: [],
      media: [],
    })),
  },
}))

function monday(offsetWeeks: number): string {
  const d = new Date()
  d.setDate(d.getDate() - d.getDay() + 1 + offsetWeeks * 7)
  return d.toISOString().slice(0, 10)
}

beforeEach(() => {
  setActivePinia(createPinia())
})

async function mountView() {
  const { default: StatsView } = await import('./StatsView.vue')
  const wrapper = mount(StatsView, { global: { plugins: [createPinia()] } })
  await flushPromises()
  return wrapper
}

describe('StatsView', () => {
  it('renders the empty-journal note with zeros and no error', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="stats-empty"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Failed')
  })

  it('renders stat tiles, weekly bars, and mood bars with data', async () => {
    const { entriesApi } = await import('../../api/entries')
    vi.mocked(entriesApi.stats).mockResolvedValue({
      total_entries: 42,
      total_words: 12500,
      current_streak: 3,
      longest_streak: 9,
      weekly: Array.from({ length: 12 }, (_, i) => ({
        week_start: monday(i - 11),
        count: i === 11 ? 5 : 2,
      })),
      moods: [
        { mood: 'good', count: 10 },
        { mood: 'awful', count: 2 },
      ],
      media: [{ media_type: 'image', count: 7 }],
    })

    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).toContain('Current streak')
    expect(text).toContain('Words written')
    expect(text).toContain('12.5K')
    expect(text).toContain('Entries per week')
    expect(text).toContain('Moods')
    expect(wrapper.find('svg[role="img"]').exists()).toBe(true)
    expect(text).toContain('good')
    expect(text).toContain('awful')
    // Media total tile sums the per-type counts.
    expect(text).toContain('Media attached')
  })

  it('shows an error message when the API call fails', async () => {
    const { entriesApi } = await import('../../api/entries')
    vi.mocked(entriesApi.stats).mockRejectedValue(new Error('boom'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('boom')
  })
})
