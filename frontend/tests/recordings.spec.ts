import { test, expect, type Page } from '@playwright/test'

/**
 * Dismiss the first-run "What's New" dialog. A fresh browser context has no
 * localStorage and the dev build reports an unknown version, so the dialog
 * reliably appears ~300ms after load and would otherwise block every click.
 * The dismiss button is labelled "Get started" on a fresh install / "Got it"
 * on an upgrade. (Shared with settings.spec.ts — kept inline to avoid a build
 * step for test helpers.)
 */
async function dismissWhatsNew(page: Page) {
  const dismiss = page.getByRole('button', { name: /^(Got it|Get started)$/ })
  await dismiss.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click()
    await page.waitForTimeout(200)
  }
}

test.describe('Voice recording', () => {
  test('floating recorder renders and arms once the entry is saved', async ({ page }) => {
    await page.goto('/')
    await dismissWhatsNew(page)

    // The calendar view opens today's entry in the editor by default. Type body
    // text so the debounced autosave creates the entry (the recorder requires a
    // saved entry before it will capture).
    const body = page.getByPlaceholder('Write your thoughts...')
    await body.waitFor({ state: 'visible', timeout: 5000 })
    await body.fill('smoke test body for the floating recorder')
    await page.waitForTimeout(3000) // autosave (2s debounce) creates the entry

    // The floating recorder FAB lives bottom-right of the editor. Its title
    // flips from "Save the entry, then record" to "Record voice memo" once the
    // entry is persisted — so the armed state also proves the entry was saved.
    const fab = page.locator('button[title="Record voice memo"]')
    await expect(fab).toBeVisible({ timeout: 5000 })
  })
})
