/**
 * Route ↔ `ui.activeView` sync (the former desync let "open entry" from
 * Timeline/Media/search render the journal editor over the wrong view, and
 * browser Back/Forward swapped the URL without updating the sidebar).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '../router'
import { useUiStore } from './ui'

// The unsaved-edit guard in router.ts only prompts when an editor is dirty;
// these tests never dirty one, so navigation always confirms.
vi.stubGlobal('confirm', () => false)

beforeEach(async () => {
  setActivePinia(createPinia())
  // Swap the lazy .vue route components for inert ones — vitest here has no
  // Vue SFC plugin, and navigation would otherwise try to import real views.
  for (const r of router.getRoutes()) {
    if (r.components) r.components.default = { render: () => null }
  }
  await router.push('/calendar')
})

describe('view ↔ route sync', () => {
  it('setView drives the route (the Timeline/Media/search jump path)', async () => {
    const ui = useUiStore()
    ui.setView('notes')
    await vi.waitFor(() => {
      expect(router.currentRoute.value.name).toBe('notes')
      expect(ui.activeView).toBe('notes')
    })
  })

  it('setView is a no-op when already on the view', async () => {
    const ui = useUiStore()
    ui.setView('calendar')
    await vi.waitFor(() => {
      expect(router.currentRoute.value.fullPath).toBe('/calendar')
      expect(ui.activeView).toBe('calendar')
    })
  })

  it('a URL navigation (Back/Forward/deep link) syncs the view flag', async () => {
    const ui = useUiStore()
    // Register the same hook main.ts installs, then navigate by URL.
    const names = ['calendar', 'timeline', 'notes', 'reminders', 'media', 'settings']
    router.afterEach((to) => {
      const name = to.name
      if (typeof name === 'string' && names.includes(name)) {
        ui.activeView = name as typeof ui.activeView
      }
    })
    await router.push('/timeline')
    expect(ui.activeView).toBe('timeline')
    await router.back()
    await vi.waitFor(() => {
      expect(ui.activeView).toBe('calendar')
    })
  })
})
