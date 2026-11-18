import { expect, type Page } from '@playwright/test'

/**
 * Shared Playwright startup helpers.
 *
 * Playwright transpiles plain TS imports natively, so test helpers need no
 * build step — specs import these directly instead of carrying inline copies.
 */

/** Dismiss the "What's New" dialog if it pops, else move on immediately. */
export async function dismissWhatsNew(page: Page) {
  const dismiss = page.getByRole('button', { name: /^(Got it|Get started)$/ })
  await dismiss.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click()
    // Wait for the dialog to finish closing instead of a fixed sleep.
    await expect(dismiss).toBeHidden({ timeout: 2000 })
  }
}

/**
 * Init script for fresh contexts: skip the memorial splash (a full-screen
 * startup overlay that holds for up to 10s and stalls every selector) and
 * mark "What's New" as seen so a version bump can't pop it over early
 * assertions. The dev server doesn't inject VITE_APP_VERSION, so the app's
 * APP_VERSION is literally 'unknown' — last-seen must equal it.
 */
export async function skipStartupOverlays(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('lifelogr-memorial-title', 'false')
    localStorage.setItem('lifelogr-update-last-seen', 'unknown')
  })
}
