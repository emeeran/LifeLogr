import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * Mount smoke test for SettingsView — setup-order / mount-crash guard.
 *
 * The tab bodies are mocked (not just stubbed): AboutTab statically imports
 * `../../../../../CHANGELOG.md?raw`, which lives outside the vitest project
 * root (frontend/) so the vitest module runner refuses to transform it
 * ("Denied ID …/CHANGELOG.md?raw"). The dev server and `vite build` both serve
 * it fine — this is a test-infrastructure limit, not an app bug — so the tabs
 * are replaced at the module graph level. What's under test is SettingsView's
 * own setup: tab-id migration, the persisted-tab computed, the deep-link
 * watcher and the settings-search index.
 */

vi.mock('./tabs/AppearanceTab.vue', () => ({
  default: { name: 'AppearanceTab', render: () => null },
}))
vi.mock('./tabs/AITab.vue', () => ({
  default: { name: 'AITab', render: () => null },
}))
vi.mock('./tabs/DataTab.vue', () => ({
  default: { name: 'DataTab', render: () => null },
}))
vi.mock('./tabs/PrivacyTab.vue', () => ({
  default: { name: 'PrivacyTab', render: () => null },
}))
vi.mock('./tabs/DedicationTab.vue', () => ({
  default: { name: 'DedicationTab', render: () => null },
}))
vi.mock('./tabs/AboutTab.vue', () => ({
  default: { name: 'AboutTab', render: () => null },
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
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
})

const TAB_STUBS = {
  AppearanceTab: true,
  AITab: true,
  DataTab: true,
  PrivacyTab: true,
  DedicationTab: true,
  AboutTab: true,
  Teleport: true,
}

describe('SettingsView mount', () => {
  it('mounts on the default tab and renders the tab bar', async () => {
    const { default: SettingsView } = await import('./SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { plugins: [createPinia()], stubs: TAB_STUBS },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.element).toBeTruthy()
    expect(wrapper.text()).toContain('Appearance')
    expect(wrapper.text()).toContain('Data')
    wrapper.unmount()
  })

  it('migrates a legacy persisted tab id instead of showing a blank screen', async () => {
    localStorage.setItem('lifelogr-settings-tab', JSON.stringify('diagnostics'))
    const { default: SettingsView } = await import('./SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { plugins: [createPinia()], stubs: TAB_STUBS },
    })
    await flushPromises()

    expect(wrapper.vm).toBeTruthy()
    expect(wrapper.text()).toContain('Appearance')
    wrapper.unmount()
    localStorage.removeItem('lifelogr-settings-tab')
  })
})
