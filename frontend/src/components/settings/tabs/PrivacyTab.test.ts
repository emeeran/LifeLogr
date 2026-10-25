import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * PrivacyTab — the weather auto-fill opt-in round-trips through
 * updateSettings({ weather: { enabled } }), and the report's generic weather
 * surface renders with the proper label.
 */

vi.mock('../../../api/system', () => ({
  getEgressReport: vi.fn(async () => ({
    cloud_ai: { leaves_device: false, note: 'local' },
    cloud_backup: { configured: [], scheduled: false, note: 'none' },
    web_clip: { leaves_device: false, note: 'url only' },
    ocr: { leaves_device: false, engine: 'tesseract', note: 'local' },
    embeddings: { leaves_device: false, note: 'local' },
    read_aloud: { leaves_device: true, provider: 'Microsoft Edge TTS', note: 'remote' },
    weather: {
      leaves_device: false,
      provider: 'Open-Meteo',
      note: 'rounded coordinates only',
    },
  })),
}))

const updateSettings = vi.fn(async () => ({ status: 'ok' }))
let currentEnabled = false
vi.mock('../../../api/settings', () => ({
  getSettings: vi.fn(async () => ({
    ai: {},
    weather: { enabled: currentEnabled },
    storage: {},
    version: 'test',
    app_name: 'LifeLogr',
  })),
  updateSettings: (...args: unknown[]) => updateSettings(...(args as [])),
}))

import { getEgressReport } from '../../../api/system'

async function mountTab() {
  const { default: PrivacyTab } = await import('./PrivacyTab.vue')
  const wrapper = mount(PrivacyTab)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  currentEnabled = false
  updateSettings.mockClear()
  vi.mocked(getEgressReport).mockClear()
})

describe('PrivacyTab weather auto-fill', () => {
  it('renders the opt-in toggle and the generic weather egress card', async () => {
    const wrapper = await mountTab()
    const text = wrapper.text()
    expect(text).toContain('Weather for geotagged entries')
    // The extra-surface card gets a proper label, not the raw key.
    expect(text).toContain('Weather auto-fill (geotagged entries)')
    expect(text).toContain('rounded coordinates only')
    expect(text).toContain('on-device') // leaves_device false → green badge
  })

  it('round-trips the toggle through updateSettings', async () => {
    const wrapper = await mountTab()
    const toggle = wrapper.find('button[role="switch"]')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    await flushPromises()
    expect(updateSettings).toHaveBeenCalledWith({ weather: { enabled: true } })
  })

  it('reverts the toggle and surfaces the error when the update fails', async () => {
    updateSettings.mockRejectedValueOnce(new Error('offline'))
    const wrapper = await mountTab()
    await wrapper.find('button[role="switch"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('offline')
    // Switch state reverted (aria-checked back to false).
    expect(wrapper.find('button[role="switch"]').attributes('aria-checked')).toBe('false')
  })
})
