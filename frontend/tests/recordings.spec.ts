import { test, expect } from '@playwright/test'
import { dismissWhatsNew, skipStartupOverlays } from './helpers'

// The memorial dedication splash (SplashScreen.vue) is a full-screen z-[200]
// overlay shown on startup while the "memorial-title" feature is on; it holds
// for up to 10s. It defaults ON, so on a fresh browser context it covers the
// editor and stalls every selector below. This spec exercises the voice
// recorder, not the splash, so disable it deterministically before first paint
// — App.vue reads `lifelogr-memorial-title` from localStorage on mount.
test.beforeEach(async ({ page }) => {
  await skipStartupOverlays(page)
})

test.describe('Voice recording', () => {
  test('floating recorder renders and arms once the entry is saved', async ({ page }) => {
    // `/` redirects to the calendar; the editor lives on the Journal view,
    // which opens today's entry by default. Type body text so the debounced
    // autosave creates the entry (the recorder requires a saved entry first).
    await page.goto('/calendar')
    await dismissWhatsNew(page)

    const body = page.getByPlaceholder('Write your thoughts...')
    await body.waitFor({ state: 'visible', timeout: 5000 })
    await body.fill('smoke test body for the floating recorder')

    // The floating recorder FAB's title flips from "Save the entry, then record"
    // to "Record voice memo" once the entry is persisted — so the armed state
    // also proves the entry was saved. Let the auto-retrying assertion absorb
    // the 2s autosave debounce instead of a fixed sleep.
    const fab = page.locator('button[title="Record voice memo"]')
    await expect(fab).toBeVisible({ timeout: 10000 })
  })
})
