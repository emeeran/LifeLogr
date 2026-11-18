import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

/**
 * ContextDrawerPanel — opt-in local context: photos listed from a chosen
 * folder, ICS events from a chosen file, attach through the media pipeline.
 * With the feature off the component is never mounted by AppShell/the editor
 * (the ui-store flag gates the only entry points), so no requests can fire.
 */

const h = vi.hoisted(() => ({
  isTauri: true,
  seeds: {} as Record<string, unknown>,
  listPhotos: vi.fn(),
  listCalendar: vi.fn(),
  uploadFromPath: vi.fn(),
}))

vi.mock('../../api/context', () => ({
  contextApi: {
    listPhotos: (...args: unknown[]) => h.listPhotos(...(args as [])),
    listCalendar: (...args: unknown[]) => h.listCalendar(...(args as [])),
  },
}))

vi.mock('../../api/media', () => ({
  mediaApi: { uploadFromPath: (...args: unknown[]) => h.uploadFromPath(...(args as [])) },
}))

vi.mock('../../utils/fileDialog', () => ({
  pickFolder: vi.fn(),
  pickFile: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  request: vi.fn(),
  // Live getter: the component's import binding re-reads it on access, so
  // tests can flip the flag per test.
  get isTauri() {
    return h.isTauri
  },
}))

vi.mock('../../stores/toast', () => ({
  useToastStore: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}))

vi.mock('@vueuse/core', () => ({
  // Real refs (so template rendering works); seeded per test. Referencing the
  // top-level `ref` here is safe — it resolves when the mock is *called*, not
  // when the hoisted factory is defined.
  useLocalStorage: (key: string, initial: unknown) =>
    ref(h.seeds[key] ?? initial) as never,
}))

async function mountPanel(props: { entryDate?: string; entryId?: number | null } = {}) {
  const { default: ContextDrawerPanel } = await import('./ContextDrawerPanel.vue')
  const wrapper = mount(ContextDrawerPanel, {
    props: { entryDate: '2026-10-25', entryId: 7, ...props },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  h.isTauri = true
  h.listPhotos.mockReset()
  h.listCalendar.mockReset()
  h.uploadFromPath.mockReset()
  for (const key of Object.keys(h.seeds)) delete h.seeds[key]
})

describe('ContextDrawerPanel', () => {
  it('makes no API calls when no folder/file is configured', async () => {
    await mountPanel()
    expect(h.listPhotos).not.toHaveBeenCalled()
    expect(h.listCalendar).not.toHaveBeenCalled()
  })

  it('loads and date-groups photos when a folder is configured', async () => {
    h.seeds['lifelogr-context-photos-dir'] = '/home/em/Pictures/roll'
    h.listPhotos.mockResolvedValue({
      items: [
        { path: '/p/b.jpg', filename: 'b.jpg', size: 10, taken_date: '2026-10-24', media_type: 'image' },
        { path: '/p/a.png', filename: 'a.png', size: 20, taken_date: '2026-10-25', media_type: 'image' },
      ],
      scanned: 2,
      truncated: false,
    })
    const wrapper = await mountPanel()
    expect(h.listPhotos).toHaveBeenCalledWith('/home/em/Pictures/roll')
    const text = wrapper.text()
    expect(text).toContain('On 2026-10-25')
    expect(text).toContain('a.png')
    // The off-day photo is grouped under its own day heading.
    expect(text).toContain('2026-10-24')
    expect(text).toContain('b.jpg')
  })

  it('attaches through mediaApi.uploadFromPath with the item path', async () => {
    h.seeds['lifelogr-context-photos-dir'] = '/home/em/Pictures/roll'
    h.listPhotos.mockResolvedValue({
      items: [
        { path: '/p/a.png', filename: 'a.png', size: 20, taken_date: '2026-10-25', media_type: 'image' },
      ],
      scanned: 1,
      truncated: false,
    })
    h.uploadFromPath.mockResolvedValue({ id: 1 })
    const wrapper = await mountPanel()
    await wrapper.find('.bg-accent\\/10').trigger('click')
    await flushPromises()
    expect(h.uploadFromPath).toHaveBeenCalledWith(7, '/p/a.png')
    expect(wrapper.emitted('refreshAttachments')).toBeTruthy()
  })

  it('lists and inserts calendar events for the entry date', async () => {
    h.seeds['lifelogr-context-ics-path'] = '/home/em/cal.ics'
    h.listCalendar.mockResolvedValue({
      items: [
        {
          uid: 'e1',
          summary: 'Standup',
          start: '2026-10-25T09:00:00',
          end: null,
          all_day: false,
          location: 'Room 2',
          description: null,
        },
      ],
      source: '/home/em/cal.ics',
      warnings: [],
    })
    const wrapper = await mountPanel()
    // Switch to the Calendar tab, then click the event row.
    const calendarTab = wrapper
      .findAll('button')
      .find((b) => b.text().includes('Calendar'))
    expect(calendarTab).toBeTruthy()
    await calendarTab!.trigger('click')
    await flushPromises()
    expect(h.listCalendar).toHaveBeenCalledWith('/home/em/cal.ics', '2026-10-25')
    const eventRow = wrapper.find('.cursor-pointer.bg-surface-hover')
    await eventRow.trigger('click')
    expect(wrapper.emitted('insertText')).toEqual([['[Standup — 09:00 — Room 2]']])
  })

  it('shows the desktop-only notice in browser builds', async () => {
    h.isTauri = false
    h.seeds['lifelogr-context-photos-dir'] = '/home/em/Pictures/roll'
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('desktop app')
    expect(h.listPhotos).not.toHaveBeenCalled()
  })
})
