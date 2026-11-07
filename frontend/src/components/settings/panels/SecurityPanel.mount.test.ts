import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * SecurityPanel mount smoke test — the no-kit warning shows exactly when
 * media encryption is on and no kit has been exported, and the export
 * flow downloads the kit file.
 */

const settingsMocks = {
  getSettings: vi.fn(),
  exportRecoveryKit: vi.fn(),
  importRecoveryKit: vi.fn(),
}

vi.mock('../../../api/settings', () => ({
  ...settingsMocks,
}))

const settingsState = {
  security: { media_encryption_enabled: false, recovery_kit_exported_at: '' },
}

async function mountPanel() {
  settingsMocks.getSettings.mockResolvedValue({
    security: { ...settingsState.security },
  })
  const { default: SecurityPanel } = await import('./SecurityPanel.vue')
  const wrapper = mount(SecurityPanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  settingsState.security = {
    media_encryption_enabled: false,
    recovery_kit_exported_at: '',
  }
  vi.mocked(settingsMocks.exportRecoveryKit).mockReset()
})

describe('SecurityPanel mount', () => {
  it('renders the export and restore rows', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    expect(text).toContain('Export recovery kit')
    expect(text).toContain('Restore from recovery kit')
    expect(text).not.toContain('no recovery kit')
    wrapper.unmount()
  })

  it('warns when encryption is on and no kit exists', async () => {
    settingsState.security = {
      media_encryption_enabled: true,
      recovery_kit_exported_at: '',
    }
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('no recovery kit')
    wrapper.unmount()
  })

  it('no warning once a kit has been exported', async () => {
    settingsState.security = {
      media_encryption_enabled: true,
      recovery_kit_exported_at: '2026-11-07T00:00:00Z',
    }
    const wrapper = await mountPanel()
    expect(wrapper.text()).not.toContain('no recovery kit')
    expect(wrapper.text()).toContain('Last exported')
    wrapper.unmount()
  })

  it('export downloads the kit and shows the generated code', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    settingsMocks.exportRecoveryKit.mockResolvedValue({
      kit: { format: 1 },
      code: 'AAAA-BBBB-CCCC-DDDD-EEEE-FFFF',
    })
    const wrapper = await mountPanel()
    const exportBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === 'Export')!
    await exportBtn.trigger('click')
    await flushPromises()
    expect(settingsMocks.exportRecoveryKit).toHaveBeenCalledWith(undefined)
    expect(wrapper.text()).toContain('AAAA-BBBB-CCCC-DDDD-EEEE-FFFF')
    expect(
      wrapper.emitted('toast')?.some(([t]) => t === 'info'),
    ).toBe(true)
    wrapper.unmount()
  })
})
