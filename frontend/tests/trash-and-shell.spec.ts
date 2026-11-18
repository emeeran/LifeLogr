import { test, expect, type APIRequestContext } from '@playwright/test'
import { dismissWhatsNew, skipStartupOverlays } from './helpers'

/**
 * UI coverage for the empty-trash feature and the editor/shell slimming:
 *
 * - TrashView's "Empty trash" button (present only when trash is non-empty),
 *   its confirm dialog, both the cancel and confirm paths, and the hard
 *   evidence: the purged entry is gone from the real backend afterwards.
 * - The journal editor no longer renders a mood selector (the field still
 *   round-trips server-side, but the UI must not offer it).
 * - The shell no longer offers the map: no sidebar item, and /map falls
 *   through the catch-all redirect to /calendar.
 *
 * Drives the real backend through the Vite /api proxy, like entries.spec.ts.
 * Serial mode: the tests share one backend, and the destructive throttle
 * (5 destructive requests / 60s per client) plus a shared trash list mean
 * order and cleanup matter.
 */
test.describe.configure({ mode: 'serial' })

async function seedEntry(
  request: APIRequestContext,
  title: string,
): Promise<number> {
  const created = await request.post('/api/v1/entries', {
    data: { entry_date: '2026-07-14', title, body: `${title} body` },
  })
  expect(created.ok(), `POST /entries → ${created.status()}`).toBeTruthy()
  const { id } = await created.json()
  return id as number
}

async function seedTrashedEntry(
  request: APIRequestContext,
  title: string,
): Promise<number> {
  const id = await seedEntry(request, title)
  const deleted = await request.delete(`/api/v1/entries/${id}`)
  expect(deleted.status(), 'soft-delete must succeed to trash the entry').toBe(204)
  return id
}

/** Wipe the whole trash via the API — one destructive request, throttle-friendly.
 *  Keeps every test independent of leftovers from earlier failed runs. */
async function cleanTrash(request: APIRequestContext) {
  const res = await request.get('/api/v1/entries/trash')
  if (res.ok() && (await res.json()).total > 0) {
    await request.delete('/api/v1/entries/trash')
  }
}

test.beforeEach(async ({ page }) => {
  await skipStartupOverlays(page)
})

test.describe('Empty trash', () => {
  test.beforeEach(async ({ request }) => {
    await cleanTrash(request)
  })

  test.afterAll(async ({ request }) => {
    await cleanTrash(request)
  })

  test('button is hidden on an empty trash, shown when items exist', async ({
    page,
    request,
  }) => {
    await page.goto('/trash')
    await dismissWhatsNew(page)
    await expect(page.getByText('Trash is empty')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Empty trash' })).toHaveCount(0)

    // A single trashed entry flips the header to the destructive action.
    const id = await seedTrashedEntry(request, 'E2E trash visibility')
    await page.goto('/trash')
    await dismissWhatsNew(page)
    await expect(page.getByText('E2E trash visibility', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Empty trash' })).toBeVisible()
    await request.delete(`/api/v1/entries/${id}/purge`)
  })

  test('cancel keeps the entry restorable', async ({ page, request }) => {
    const id = await seedTrashedEntry(request, 'E2E trash cancel')
    await page.goto('/trash')
    await dismissWhatsNew(page)
    await page.getByRole('button', { name: 'Empty trash' }).click()
    await expect(page.getByText('Empty trash?')).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()

    await expect(page.getByText('Empty trash?')).toHaveCount(0)
    await expect(page.getByText('E2E trash cancel', { exact: true })).toBeVisible()

    // Still soft-deleted, not purged: the API can restore it.
    const restored = await request.post(`/api/v1/entries/${id}/restore`)
    expect(restored.ok(), 'cancelled empty-trash must leave the entry restorable').toBeTruthy()
  })

  test('confirming destroys the entries for good', async ({ page, request }) => {
    const id = await seedTrashedEntry(request, 'E2E trash confirm')
    await page.goto('/trash')
    await dismissWhatsNew(page)

    await page.getByRole('button', { name: 'Empty trash' }).click()
    await expect(page.getByText('Empty trash?')).toBeVisible()
    await page.getByRole('button', { name: 'Confirm' }).click()

    await expect(page.getByText('Trash is empty')).toBeVisible()

    // Hard proof against the real backend: purged entries answer 404.
    const check = await request.get(`/api/v1/entries/${id}`)
    expect(check.status(), 'confirmed empty-trash must purge the entry').toBe(404)
  })
})

test.describe('Slimmed-down UI', () => {
  test('the journal editor has no mood selector', async ({ page }) => {
    await page.goto('/calendar')
    await dismissWhatsNew(page)
    // The editor header no longer offers mood selection.
    await expect(page.getByLabel('Mood')).toHaveCount(0)
    await expect(page.locator('select[title="Mood"]')).toHaveCount(0)
  })

  test('the map is gone from the shell', async ({ page }) => {
    await page.goto('/calendar')
    await dismissWhatsNew(page)
    // No sidebar nav item labelled Map.
    await expect(page.locator('nav').getByText('Map', { exact: true })).toHaveCount(0)

    // The /map route is gone: the catch-all redirects to the calendar.
    await page.goto('/map')
    await page.waitForURL(/\/calendar$/)
  })
})
