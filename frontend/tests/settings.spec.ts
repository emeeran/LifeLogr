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
    await page.waitForTimeout(200)
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
    // Navigate to settings - click the settings icon/link in the sidebar
    await page.locator('text=Settings').first().click()
    await page.waitForTimeout(500)
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
    await page.waitForTimeout(800)

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

  // ── Data Tab ──
  test('Data tab: sections, descriptions, skeleton loading', async ({ page }) => {
    await tab(page, 'Data').click()
    await page.waitForTimeout(800)

    // Storage section
    await expect(page.getByText('Storage', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Disk usage and entry statistics')).toBeVisible()

    // Import / Export section
    await expect(page.getByText('Import / Export', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Bring entries in or export your journal')).toBeVisible()

    // Backup section (.first(): "Backup" also appears as an action label)
    await expect(page.getByText('Backup', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Local archive and scheduled backups')).toBeVisible()

    // Cloud section with description
    await expect(page.getByText('Cloud', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Sync your journal to cloud storage')).toBeVisible()

    // Sync section
    await expect(page.getByText('Sync', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Manage data synchronization queue')).toBeVisible()

    // Cloud empty state (if no configs)
    const emptyState = page.getByText('No cloud backups configured')
    if (await emptyState.isVisible().catch(() => false)) {
      // Should have a hint below
      await expect(page.getByText('Click Add to connect a cloud provider')).toBeVisible()
    }
  })

  // ── Features Tab ──
  test('Features tab: TTS voice selector, notifications', async ({ page }) => {
    await tab(page, 'Features').click()
    await page.waitForTimeout(800)

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
    await page.waitForTimeout(500)

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
    await page.waitForTimeout(500)

    // Check that selects have the settings-select class
    const styledSelects = page.locator('select.settings-select')
    await expect(styledSelects.count()).resolves.toBeGreaterThanOrEqual(2)

    // Check that inputs have the settings-input class
    const styledInputs = page.locator('input.settings-input')
    await expect(styledInputs.count()).resolves.toBeGreaterThanOrEqual(1)
  })

  // ── Keyboard navigation ──
  test('Focus rings on tab navigation', async ({ page }) => {
    await tab(page, 'General').click()
    await page.waitForTimeout(500)

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
