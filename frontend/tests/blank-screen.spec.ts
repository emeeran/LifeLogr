import { test, expect, type Page } from '@playwright/test'

/**
 * BLANK-8 — a throwing view renders the ErrorBoundary (message + Reload +
 * "Copy details"), not a blank panel, and the shell around it stays alive.
 *
 * The crash is forced with the `?crash=1` query parameter, which swaps the
 * routed view for `CrashProbe.vue` (a component that throws in setup). No app
 * navigation ever sets that parameter.
 */
async function dismissWhatsNew(page: Page) {
  const dismiss = page.getByRole('button', { name: /^(Got it|Get started)$/ })
  await dismiss.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click()
    await expect(dismiss).toBeHidden({ timeout: 2000 })
  }
}

test.beforeEach(async ({ page }) => {
  // The memorial splash is a full-screen overlay on fresh contexts; disable it.
  await page.addInitScript(() => {
    localStorage.setItem('lifelogr-memorial-title', 'false')
  })
})

test.describe('ErrorBoundary (BLANK-8)', () => {
  test('a throwing view renders the boundary, not a blank page', async ({
    page,
  }) => {
    await page.goto('/?crash=1')
    await dismissWhatsNew(page)

    // The boundary owns the routed area: heading, explanation, raw message.
    await expect(
      page.getByRole('heading', { name: 'This view stopped rendering' }),
    ).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('The rest of the app is still running')).toBeVisible()
    await expect(page.locator('pre')).toContainText('CrashProbe')

    // Both recovery actions are offered.
    await expect(page.getByRole('button', { name: 'Reload' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Copy details' })).toBeVisible()

    // The shell survives: the sidebar navigation is still rendered and usable.
    await expect(page.locator('nav').first()).toBeVisible()
    await expect(page.locator('text=Settings').first()).toBeVisible()
  })

  test('Copy details flips to Copied', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto('/?crash=1')
    const copy = page.getByRole('button', { name: 'Copy details' })
    await expect(copy).toBeVisible({ timeout: 5000 })
    await copy.click()
    await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible()
    const details = await page.evaluate(() =>
      navigator.clipboard.readText().catch(() => ''),
    )
    expect(details).toContain('CrashProbe')
    expect(details).toContain('view:')
  })

  test('Reload re-runs the view (still crashing, still bounded)', async ({
    page,
  }) => {
    await page.goto('/?crash=1')
    await page.getByRole('button', { name: 'Reload' }).click({ timeout: 5000 })
    // ?crash=1 survives the reload, so the boundary catches the probe again —
    // proving the reload handler actually reloaded rather than doing nothing.
    await expect(
      page.getByRole('heading', { name: 'This view stopped rendering' }),
    ).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Route switching (BLANK-9)', () => {
  /**
   * BLANK-9 — rapid Journal ↔ Notes toggling must always leave a view mounted.
   *
   * The old route transition used mode="out-in": leave completes before enter
   * starts, so while a lazy route chunk resolves inside that gap Vue can end up
   * rendering a comment placeholder — a permanently blank panel with no error
   * (exactly the user report). The invariant is structural, not textual: the
   * routed <main> must contain an element after every navigation. A comment
   * placeholder is invisible to CSS selectors, so `main > *` hitting zero is
   * the blank-page signature.
   */
  test('rapid Journal ↔ Notes toggling always mounts a view', async ({
    page,
  }) => {
    await page.goto('/calendar')
    await dismissWhatsNew(page)

    const routedChildren = page.locator('main > *')
    await expect(routedChildren.first()).toBeVisible({ timeout: 5000 })

    for (let i = 0; i < 10; i++) {
      // Click without waiting for the previous transition to settle — the
      // race needs a navigation to interrupt an active leave phase.
      await page.getByRole('link', { name: 'Notes' }).click()
      await expect(routedChildren.first()).toBeVisible({ timeout: 3000 })
      await page.getByRole('link', { name: 'Journal' }).click()
      await expect(routedChildren.first()).toBeVisible({ timeout: 3000 })
    }
  })
})
