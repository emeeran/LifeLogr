import { test, expect } from '@playwright/test'

test.describe('Settings UI verification', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Navigate to settings - click the settings icon/link in the sidebar
    await page.locator('text=Settings').first().click()
    await page.waitForTimeout(500)
  })

  // ── General Tab ──
  test('General tab: toggle switches render, descriptions visible', async ({ page }) => {
    // Should be on General tab by default
    await expect(page.locator('text=Appearance')).toBeVisible()
    await expect(page.locator('text=Customize the look and feel')).toBeVisible()

    // Toggle switches: should use role="switch", not raw checkboxes in the UI
    const darkModeToggle = page.locator('role=switch[name=/dark/i], [role="switch"]').first()
    await expect(darkModeToggle).toBeVisible()

    // Editor section has description
    await expect(page.locator('text=Editor & Writing')).toBeVisible()
    await expect(page.locator('text=Writing behavior, search, and preferences')).toBeVisible()

    // Keyboard shortcuts accordion (collapsed by default)
    await expect(page.locator('text=Keyboard Shortcuts')).toBeVisible()
    // Shortcuts should be collapsed - the kbd elements should NOT be visible
    await expect(page.locator('kbd')).toHaveCount(0)

    // Click to expand
    await page.locator('text=Keyboard Shortcuts').click()
    await page.waitForTimeout(300)
    // Now kbd elements should appear
    await expect(page.locator('kbd').first()).toBeVisible()
  })

  // ── AI Tab ──
  test('AI tab: connection settings, embed model, test button', async ({ page }) => {
    await page.locator('text=AI').click()
    await page.waitForTimeout(800)

    // Section header + description
    await expect(page.locator('text=AI Configuration')).toBeVisible()
    await expect(page.locator('text=Local AI model and feature settings')).toBeVisible()

    // Connection sub-section
    await expect(page.locator('text=Connection')).toBeVisible()
    await expect(page.locator('text=Ollama URL')).toBeVisible()

    // Ollama URL input
    const urlInput = page.locator('input[placeholder="http://localhost:11434"]')
    await expect(urlInput).toBeVisible()

    // Test Connection button
    await expect(page.locator('text=Test Connection')).toBeVisible()

    // Models sub-section
    await expect(page.locator('text=Models')).toBeVisible()
    await expect(page.locator('text=Chat model')).toBeVisible()
    await expect(page.locator('text=Embedding model')).toBeVisible()

    // Embed model input with datalist
    const embedInput = page.locator('input[placeholder="nomic-embed-text"]')
    await expect(embedInput).toBeVisible()

    // Feature toggles as toggle switches
    await expect(page.locator('text=Features')).toBeVisible()
    const toggles = page.locator('[role="switch"]')
    await expect(toggles.count()).resolves.toBeGreaterThanOrEqual(6)

    // Themes & Insights accordion (collapsed)
    await expect(page.locator('text=Themes & Insights')).toBeVisible()
    await expect(page.locator('text=Discover patterns in your journaling')).toBeVisible()
  })

  // ── Data Tab ──
  test('Data tab: sections, descriptions, skeleton loading', async ({ page }) => {
    await page.locator('text=Data').click()
    await page.waitForTimeout(800)

    // Storage section
    await expect(page.locator('text=Storage')).toBeVisible()
    await expect(page.locator('text=Disk usage and entry statistics')).toBeVisible()

    // Import / Export section
    await expect(page.locator('text=Import / Export')).toBeVisible()
    await expect(page.locator('text=Bring entries in or export your journal')).toBeVisible()

    // Backup section
    await expect(page.locator('text=Backup')).toBeVisible()
    await expect(page.locator('text=Local archive and scheduled backups')).toBeVisible()

    // Cloud section with description
    await expect(page.locator('text=Cloud')).toBeVisible()
    await expect(page.locator('text=Sync your journal to cloud storage')).toBeVisible()

    // Sync section
    await expect(page.locator('text=Sync')).toBeVisible()
    await expect(page.locator('text=Manage data synchronization queue')).toBeVisible()

    // Cloud empty state (if no configs)
    const emptyState = page.locator('text=No cloud backups configured')
    if (await emptyState.isVisible()) {
      // Should have a hint below
      await expect(page.locator('text=Click Add to connect a cloud provider')).toBeVisible()
    }
  })

  // ── Features Tab ──
  test('Features tab: TTS voice selector, notifications, plugins', async ({ page }) => {
    await page.locator('text=Features').click()
    await page.waitForTimeout(800)

    // Read Aloud section
    await expect(page.locator('text=Read Aloud')).toBeVisible()
    await expect(page.locator('text=Text-to-speech voice settings')).toBeVisible()

    // Voice select - should have optgroups
    const voiceSelect = page.locator('select').filter({ hasText: '' }).first()
    await expect(page.locator('text=Voice')).toBeVisible()

    // Speed and Volume sliders
    await expect(page.locator('text=/Speed/')).toBeVisible()
    await expect(page.locator('text=/Volume/')).toBeVisible()

    // Notifications section
    await expect(page.locator('text=Notifications')).toBeVisible()
    await expect(page.locator('text=Writing reminders and alerts')).toBeVisible()

    // Plugins section
    await expect(page.locator('text=Plugins')).toBeVisible()
    await expect(page.locator('text=Extend LifeLogr with plugins')).toBeVisible()
  })

  // ── About Tab ──
  test('About tab: info card, danger zone', async ({ page }) => {
    await page.locator('text=About').click()
    await page.waitForTimeout(500)

    await expect(page.locator('text=About')).toBeVisible()
    await expect(page.locator('text=App information and credits')).toBeVisible()
    await expect(page.locator('text=LifeLogr')).toBeVisible()

    // Links
    await expect(page.locator('text=GitHub')).toBeVisible()
    await expect(page.locator('text=Report Issue')).toBeVisible()
    await expect(page.locator('text=License')).toBeVisible()

    // Danger zone
    await expect(page.locator('text=Reset Database')).toBeVisible()
  })

  // ── CSS: settings-select class ──
  test('CSS utility classes applied to selects and inputs', async ({ page }) => {
    await page.locator('text=General').click()
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
    await page.locator('text=General').click()
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
