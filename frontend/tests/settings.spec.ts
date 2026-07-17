import { test, expect, type Page } from '@playwright/test'

/**
 * Dismiss the first-run "What's New" dialog. A fresh browser context has no
 * localStorage and the dev build reports an unknown version, so the dialog
 * reliably appears ~300ms after load and would otherwise block every click.
 * The dismiss button is labelled "Get started" on a fresh install / "Got it"
 * on an upgrade.
 */
async function dismissWhatsNew(page: Page) {
  const dismiss = page.getByRole('button', { name: /^(Got it|Get started)$/ })
  await dismiss.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click()
    // Wait for the dialog to finish closing instead of a fixed sleep.
    await expect(dismiss).toBeHidden({ timeout: 2000 })
  }
}

/** Click a settings tab in the vertical nav (scoped so it can't match content). */
function tab(page: Page, name: string) {
  return page.locator('nav').getByRole('button', { name, exact: true })
}

test.describe('Settings UI verification', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await dismissWhatsNew(page)
    // Click the Settings link in the sidebar. The per-test assertions and the
    // tab() clicks below are auto-retrying, so they wait for SettingsView to
    // mount on their own — no fixed sleep needed here.
    await page.locator('text=Settings').first().click()
  })

  // ── General Tab ──
  test('General tab: toggle switches render, descriptions visible', async ({ page }) => {
    // Should be on General tab by default
    await expect(page.getByText('Appearance', { exact: true })).toBeVisible()
    await expect(page.getByText('Customize the look and feel')).toBeVisible()

    // Toggle switches: should use role="switch", not raw checkboxes in the UI
    const darkModeToggle = page.locator('[role="switch"]').first()
    await expect(darkModeToggle).toBeVisible()

    // Editor section has description
    await expect(page.getByText('Editor & Writing', { exact: true })).toBeVisible()
    await expect(page.getByText('Writing behavior, search, and preferences')).toBeVisible()

    // Keyboard shortcuts accordion (open by default — its <kbd> shortcuts are
    // rendered in-DOM via a CSS grid collapse).
    await expect(page.getByText('Keyboard Shortcuts', { exact: true })).toBeVisible()
    await expect(page.locator('kbd').first()).toBeVisible()
  })

  // ── AI Tab ──
  test('AI tab: connection settings, embed model, test button', async ({ page }) => {
    await tab(page, 'AI').click()
    // toBeVisible auto-retries as the tab mounts — no fixed sleep needed.

    // Section header + description
    await expect(page.getByText('AI Configuration', { exact: true })).toBeVisible()
    await expect(page.getByText('Local AI model and feature settings')).toBeVisible()

    // Connection sub-section
    await expect(page.getByText('Connection', { exact: true })).toBeVisible()
    await expect(page.getByText('Ollama URL', { exact: true })).toBeVisible()

    // Ollama URL input
    const urlInput = page.locator('input[placeholder="http://localhost:11434"]')
    await expect(urlInput).toBeVisible()

    // Test Connection button
    await expect(page.getByRole('button', { name: 'Test Connection' })).toBeVisible()

    // Models sub-section
    await expect(page.getByText('Models', { exact: true })).toBeVisible()
    await expect(page.getByText('Chat model', { exact: true })).toBeVisible()
    await expect(page.getByText('Embedding model', { exact: true })).toBeVisible()

    // Embed model input with datalist
    const embedInput = page.locator('input[placeholder="nomic-embed-text"]')
    await expect(embedInput).toBeVisible()

    // Feature toggles as toggle switches (the "Features" section header collides
    // with the nav tab label, so verify the section via its toggles instead).
    const toggles = page.locator('[role="switch"]')
    await expect(toggles.count()).resolves.toBeGreaterThanOrEqual(6)

    // Themes & Insights accordion (title is in the always-visible header; its
    // description lives inside the collapsed body, so isn't asserted here)
    await expect(page.getByText('Themes & Insights', { exact: true })).toBeVisible()
  })

  // ── Data & Backup Tab ──
  // The old separate "Data" and "Backup" nav tabs were merged into a single
  // "Data & Backup" tab whose body is a Storage / Import-Export / Backups pill
  // sub-nav. Assert the nav tab opens, the default Storage panel renders, and
  // that drilling into the Backups pill surfaces the backup sections.
  test('Data & Backup tab: storage and backup sections render', async ({ page }) => {
    await tab(page, 'Data & Backup').click()

    // Storage is the default pill → its section renders immediately.
    await expect(page.getByText('Storage', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Disk usage and entry statistics')).toBeVisible()

    // Switch to the Backups pill → the backup sections render (toBeVisible
    // waits for the swap; no fixed sleep).
    await page.getByRole('button', { name: 'Backups', exact: true }).click()
    await expect(page.getByText('Local Backup', { exact: true })).toBeVisible()
    await expect(page.getByText('Scheduled Backup', { exact: true })).toBeVisible()
    await expect(page.getByText('Cloud Backup', { exact: true })).toBeVisible()
  })

  // ── Features Tab ──
  test('Features tab: TTS voice selector, notifications', async ({ page }) => {
    await tab(page, 'Features').click()

    // Read Aloud section
    await expect(page.getByText('Read Aloud', { exact: true })).toBeVisible()
    await expect(page.getByText('Text-to-speech voice settings')).toBeVisible()

    // Voice select label
    await expect(page.getByText('Voice', { exact: true })).toBeVisible()

    // Speed and Volume sliders
    await expect(page.getByText(/Speed/).first()).toBeVisible()
    await expect(page.getByText(/Volume/).first()).toBeVisible()

    // Notifications section
    await expect(page.getByText('Notifications', { exact: true })).toBeVisible()
    await expect(page.getByText('Writing reminders and alerts')).toBeVisible()
  })

  // ── About Tab ──
  test('About tab: info card, danger zone', async ({ page }) => {
    await tab(page, 'About').click()

    // Hero: brand name + tagline
    await expect(page.locator('h2').filter({ hasText: 'LifeLogr' })).toBeVisible()
    await expect(page.getByText('Privacy-first, offline-first journaling for Linux')).toBeVisible()

    // Links
    await expect(page.getByRole('link', { name: 'GitHub' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Report Issue' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'License' })).toBeVisible()

    // Danger zone
    await expect(page.getByText('Reset Database', { exact: true })).toBeVisible()
  })

  // ── CSS: settings-select class ──
  test('CSS utility classes applied to selects and inputs', async ({ page }) => {
    await tab(page, 'General').click()

    // A count check doesn't auto-retry like toBeVisible, so wait for at least
    // one styled control to render before counting them.
    const styledSelects = page.locator('select.settings-select')
    await expect(styledSelects.first()).toBeVisible()
    await expect(styledSelects.count()).resolves.toBeGreaterThanOrEqual(2)

    const styledInputs = page.locator('input.settings-input')
    await expect(styledInputs.first()).toBeVisible()
    await expect(styledInputs.count()).resolves.toBeGreaterThanOrEqual(1)
  })

  // ── Keyboard navigation ──
  test('Focus rings on tab navigation', async ({ page }) => {
    await tab(page, 'General').click()
    // Wait for the General tab to render before driving keyboard focus onto it.
    await expect(page.getByText('Appearance', { exact: true })).toBeVisible()

    // Tab to first interactive element and check focus outline
    await page.keyboard.press('Tab')

    // Get the focused element's computed outline style
    const hasFocusRing = await page.evaluate(() => {
      const el = document.activeElement
      if (!el) return false
      const style = window.getComputedStyle(el)
      return style.outlineWidth !== '0px' || style.outlineStyle !== 'none'
    })
    // Focus ring should be visible (applied by global CSS)
    expect(hasFocusRing).toBeTruthy()
  })
})
