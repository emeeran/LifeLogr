import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * MaintenancePanel mount smoke test — dedupe/vacuum rows render,
 * and the startup system check (absorbed from the former Diagnostics pill)
 * shows its summary chips with Re-check / Rebuild index actions.
 */

vi.mock('../../../api/settings', () => ({
  vacuumDatabase: vi.fn(async () => ({ reclaimed_bytes: 0 })),
  getSettings: vi.fn(async () => ({
    security: { media_encryption_enabled: true },
  })),
  encryptMedia: vi.fn(async (dryRun: boolean) => ({
    dry_run: dryRun,
    candidates: 0,
    plaintext_bytes: 0,
    stale_thumbs: 0,
    updated: 0,
    thumbs_purged: 0,
    errors: [],
  })),
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
    expect(text).toContain('Encrypt attachments of encrypted items')
    expect(text).toContain('System Check')
    expect(text).toContain('Rebuild index')
    expect(text).toContain('Re-check')
    expect(text).toContain('Database')
    wrapper.unmount()
  })

  it('hides the media-encryption row when the flag is off', async () => {
    const { getSettings } = await import('../../../api/settings')
    vi.mocked(getSettings).mockResolvedValueOnce({
      security: { media_encryption_enabled: false },
    } as never)
    const wrapper = await mountPanel()
    expect(wrapper.text()).not.toContain('Encrypt attachments of encrypted items')
    wrapper.unmount()
  })

  it('media encryption: preview reports, second click applies and toasts', async () => {
    const { encryptMedia } = await import('../../../api/settings')
    vi.mocked(encryptMedia).mockClear()
    vi.mocked(encryptMedia).mockResolvedValueOnce({
      dry_run: true,
      candidates: 2,
      plaintext_bytes: 2048,
      stale_thumbs: 1,
      updated: 0,
      thumbs_purged: 0,
      errors: [],
    })
    const wrapper = await mountPanel()
    // Two rows render a "Preview" button (titles backfill, media encryption) —
    // take the last, which is the encryption row.
    const previews = wrapper
      .findAll('button')
      .filter((b) => b.text().trim() === 'Preview')
    const button = previews[previews.length - 1]!
    await button.trigger('click')
    await flushPromises()
    expect(encryptMedia).toHaveBeenCalledWith(true)
    expect(wrapper.text()).toContain('2 files (2 KB, 1 old thumbnail)')

    vi.mocked(encryptMedia).mockResolvedValueOnce({
      dry_run: false,
      candidates: 2,
      plaintext_bytes: 2048,
      stale_thumbs: 1,
      updated: 2,
      thumbs_purged: 1,
      errors: [],
    })
    const apply = wrapper.findAll('button').find((b) => b.text().trim() === 'Apply')!
    await apply.trigger('click')
    await flushPromises()
    expect(encryptMedia).toHaveBeenCalledWith(false)
    expect(
      wrapper.emitted('toast')?.some(
        ([t, m]) => t === 'success' && String(m).includes('Encrypted 2 attachments'),
      ),
    ).toBe(true)
    wrapper.unmount()
  })

  it('loads the system-health report on mount', async () => {
    await mountPanel()
    expect(healthMocks.load).toHaveBeenCalledTimes(1)
  })

  it('re-checks the system on demand and toasts the outcome', async () => {
    const wrapper = await mountPanel()
    const recheckButton = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === 'Re-check')!
    await recheckButton.trigger('click')
    await flushPromises()
    expect(healthMocks.refresh).toHaveBeenCalledTimes(1)
    expect(
      wrapper.emitted('toast')?.some(([t, m]) => t === 'success' && String(m).includes('All checks passed')),
    ).toBe(true)
    wrapper.unmount()
  })
})
