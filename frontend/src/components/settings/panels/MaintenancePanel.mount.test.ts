import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * MaintenancePanel mount smoke test — dedupe/vacuum/integrity rows render,
 * and the startup system check (absorbed from the former Diagnostics pill)
 * shows its summary chips with Re-check / Rebuild index actions.
 */

const checkIntegrity = vi.fn(async () => ({ status: 'ok', message: 'fine' }))
vi.mock('../../../api/settings', () => ({
  vacuumDatabase: vi.fn(async () => ({ reclaimed_bytes: 0 })),
  checkIntegrity: (...args: unknown[]) => checkIntegrity(...(args as [])),
}))
vi.mock('../../../api/entries', () => ({
  entriesApi: { deduplicate: vi.fn() },
}))
const healthMocks = {
  load: vi.fn(),
  refresh: vi.fn(async () => {}),
  rebuildIndex: vi.fn(async () => {}),
}
vi.mock('../../../stores/systemHealth', () => ({
  useSystemHealthStore: () => ({
    loaded: false,
    refreshing: false,
    report: {
      ran_at: '2026-10-26T00:00:00Z',
      checks: [
        { id: 'db', status: 'ok', label: 'Database', detail: 'ok', hint: null },
      ],
      summary: { ok: 1, warn: 0, error: 0 },
    },
    hasIssues: false,
    issueCount: 0,
    summary: { ok: 1, warn: 0, error: 0 },
    ...healthMocks,
  }),
}))

async function mountPanel() {
  const { default: MaintenancePanel } = await import('./MaintenancePanel.vue')
  const wrapper = mount(MaintenancePanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  checkIntegrity.mockClear()
  healthMocks.load.mockClear()
  healthMocks.refresh.mockClear()
  healthMocks.rebuildIndex.mockClear()
})

describe('MaintenancePanel mount', () => {
  it('renders the maintenance rows and the system-check section', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    expect(text).toContain('Remove duplicates')
    expect(text).toContain('Compact database')
    expect(text).toContain('Check integrity')
    expect(text).toContain('System Check')
    expect(text).toContain('Rebuild index')
    expect(text).toContain('Re-check')
    expect(text).toContain('Database')
    wrapper.unmount()
  })

  it('loads the system-health report on mount', async () => {
    await mountPanel()
    expect(healthMocks.load).toHaveBeenCalledTimes(1)
  })

  it('toasts OK after a passing integrity check', async () => {
    const wrapper = await mountPanel()
    const checkButton = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === 'Check')!
    await checkButton.trigger('click')
    await flushPromises()
    expect(checkIntegrity).toHaveBeenCalledTimes(1)
    expect(
      wrapper.emitted('toast')?.some(([t, m]) => t === 'success' && String(m).includes('integrity: OK')),
    ).toBe(true)
    wrapper.unmount()
  })
})
