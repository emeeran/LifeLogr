import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * DataTab mount test — the five-pill sub-nav swaps panels, and a pill id
 * persisted before the overhaul ('import-export', 'backups', 'diagnostics')
 * migrates to its new home instead of rendering a blank tab.
 */

vi.mock('../panels/StoragePanel.vue', () => ({
  default: { name: 'StoragePanel', template: '<div data-panel="storage"/>' },
}))
vi.mock('../panels/ImportPanel.vue', () => ({
  default: { name: 'ImportPanel', template: '<div data-panel="import"/>' },
}))
vi.mock('../panels/ExportPanel.vue', () => ({
  default: { name: 'ExportPanel', template: '<div data-panel="export"/>' },
}))
vi.mock('../panels/BackupRestorePanel.vue', () => ({
  default: {
    name: 'BackupRestorePanel',
    template: '<div data-panel="backup-restore"/>',
  },
}))
vi.mock('../panels/MaintenancePanel.vue', () => ({
  default: {
    name: 'MaintenancePanel',
    template: '<div data-panel="maintenance"/>',
  },
}))

async function mountTab() {
  const { default: DataTab } = await import('./DataTab.vue')
  const wrapper = mount(DataTab)
  await flushPromises()
  return wrapper
}

function activePanel(wrapper: Awaited<ReturnType<typeof mountTab>>) {
  return wrapper.find('[data-panel]').attributes('data-panel')
}

beforeEach(() => {
  localStorage.removeItem('lifelogr-data-backup-pill')
})

describe('DataTab pills', () => {
  it('defaults to the Import pill and swaps panels on click', async () => {
    const wrapper = await mountTab()
    expect(activePanel(wrapper)).toBe('import')

    await wrapper
      .findAll('[role="tab"]')
      .find((t) => t.text() === 'Backup & Restore')!
      .trigger('click')
    expect(activePanel(wrapper)).toBe('backup-restore')

    await wrapper
      .findAll('[role="tab"]')
      .find((t) => t.text() === 'Maintenance')!
      .trigger('click')
    expect(activePanel(wrapper)).toBe('maintenance')
    wrapper.unmount()
  })

  it('migrates legacy persisted pill ids', async () => {
    for (const [legacy, expected] of [
      ['import-export', 'import'],
      ['backups', 'backup-restore'],
      ['diagnostics', 'maintenance'],
    ] as const) {
      // String-typed useLocalStorage refs persist raw (no JSON quotes) —
      // write the value the way the app itself would.
      localStorage.setItem('lifelogr-data-backup-pill', legacy)
      const wrapper = await mountTab()
      expect(activePanel(wrapper)).toBe(expected)
      wrapper.unmount()
      localStorage.removeItem('lifelogr-data-backup-pill')
    }
  })
})
