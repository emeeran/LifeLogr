import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for RemindersView — setup-order / mount-crash guard.
 */

vi.mock('../../api/reminders', () => ({
  listReminders: vi.fn(async () => []),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  deleteReminder: vi.fn(),
  testNotification: vi.fn(async () => ({ sent: false })),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia
  }
  window.confirm = vi.fn(() => true)
})

describe('RemindersView mount', () => {
  it('mounts with no reminders and shows the empty state', async () => {
    const { default: RemindersView } = await import('./RemindersView.vue')
    const wrapper = mount(RemindersView, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    expect(wrapper.text()).toContain('Reminder')
    wrapper.unmount()
  })

  it('mounts with existing reminders and renders their rows', async () => {
    // Seeded through the API mock: the view's onMounted fetchAll() overwrites
    // any pre-seeded store state with the server's answer.
    const { listReminders } = await import('../../api/reminders')
    vi.mocked(listReminders).mockResolvedValue([
      {
        id: 1,
        title: 'Evening journal',
        message: 'Write your day',
        reminder_time: '21:00',
        days_of_week: '1,2,3,4,5',
        is_active: true,
        last_fired_at: null,
      },
    ] as never)

    const { default: RemindersView } = await import('./RemindersView.vue')
    const wrapper = mount(RemindersView, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('Evening journal')
    wrapper.unmount()
  })
})
