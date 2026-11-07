import { test, expect, type Page } from '@playwright/test'

/**
 * RESIZE-7 — pasted-media sizing survives the round trip:
 *   1. an entry whose body pins an image to 320×200 renders its preview from
 *      the `/thumb` source (w ≤ 640, BLANK-4), never the `/file` source;
 *   2. dragging the corner grip persists a new `?w=&h=` into the body;
 *   3. after a reload the size is identical, and 320 px still decodes `/thumb`.
 *
 * The "paste" step is replaced by seeding the body through the API with the
 * exact markdown a paste produces (paste itself is exercised by the unit
 * tests); the grip drag is the real pointer gesture.
 */

// 1×1 PNG (transparent) — intrinsic size is irrelevant: the grip writes
// explicit pixel sizes onto the wrapper, and the assertions are about URLs
// and wrapper geometry, not decoded pixels.
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

async function dismissWhatsNew(page: Page) {
  const dismiss = page.getByRole('button', { name: /^(Got it|Get started)$/ })
  await dismiss.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})
  if (await dismiss.isVisible().catch(() => false)) {
    await dismiss.click()
    await expect(dismiss).toBeHidden({ timeout: 2000 })
  }
}

/** Today's date in local time — the Journal view opens "today's" entry. */
function today(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const SEED_TITLE = 'RESIZE-7 seed'

/** Create (or reuse) today's seed entry with a pinned 320×200 image.

 *  Idempotent: a date with *several* entries makes the calendar open a picker
 *  instead of the entry, so leftover seeds from previous runs are deleted and
 *  exactly one remains. */
async function createEntryWithImage(
  request: import('@playwright/test').APIRequestContext,
): Promise<{ entryId: number; mediaId: number }> {
  const list = await request.get(`/api/v1/entries?limit=100&offset=0`)
  expect(list.ok(), `GET /entries → ${list.status()}`).toBeTruthy()
  const { items } = await list.json()
  const seeds: { id: number }[] = items.filter(
    (e: { title: string | null }) => e.title === SEED_TITLE,
  )
  for (const stale of seeds.slice(1)) await request.delete(`/api/v1/entries/${stale.id}`)
  let entry: { id: number }
  if (seeds.length > 0) {
    entry = seeds[0]
  } else {
    const created = await request.post('/api/v1/entries', {
      data: { entry_date: today(), title: SEED_TITLE, body: 'seed' },
    })
    expect(created.ok(), `POST /entries → ${created.status()}`).toBeTruthy()
    entry = await created.json()
  }

  const uploaded = await request.post('/api/v1/media', {
    multipart: {
      entry_id: String(entry.id),
      file: { name: 'dot.png', mimeType: 'image/png', buffer: PNG_1X1 },
    },
  })
  expect(uploaded.ok(), `POST /media → ${uploaded.status()}`).toBeTruthy()
  const media = await uploaded.json()

  const patched = await request.patch(`/api/v1/entries/${entry.id}`, {
    data: {
      body: `![dot](/api/v1/media/${media.id}/file?w=320&h=200)`,
    },
  })
  expect(patched.ok(), `PATCH /entries → ${patched.status()}`).toBeTruthy()
  return { entryId: entry.id, mediaId: media.id }
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('lifelogr-memorial-title', 'false')
  })
})

test.describe('Media resize round trip (RESIZE-7)', () => {
  // Wide viewport: the editor rail clamps media to the panel width
  // (`max-width: 100%`), which would shrink the seeded 320 px image and
  // change the keyboard-resize arithmetic below.
  test.use({ viewport: { width: 1680, height: 1050 } })

  test('grip drag persists ?w=&h= and downsized images decode /thumb', async ({
    page,
    request,
  }) => {
    const { entryId } = await createEntryWithImage(request)

    // Track what the preview actually fetches.
    const fetched: string[] = []
    page.on('request', (r) => {
      if (r.url().includes('/api/v1/media/')) fetched.push(r.url())
    })

    await page.goto('/calendar')
    await dismissWhatsNew(page)

    // The journal editor starts on a fresh draft (ui store default), so open
    // the seeded entry through the calendar: one click on the day's cell opens
    // its entry (CalendarCell.handleClick → openEntry).
    await page.getByText('RESIZE-7 seed').first().click({ timeout: 10000 })

    const previewToggle = page.locator('button[title="Preview mode"]')
    await previewToggle.waitFor({ state: 'visible', timeout: 10000 })

    // The textarea holds the seeded body; flip to preview.
    const bodyInput = page.getByPlaceholder('Write your thoughts...')
    await expect(bodyInput).toHaveValue(/w=320&h=200/, { timeout: 10000 })
    await previewToggle.click()

    // w=320 ≤ 640 → the rendered img src must be the thumbnail source.
    const img = page.locator('.rmedia img')
    await expect(img).toBeVisible({ timeout: 5000 })
    await expect(img).toHaveAttribute('src', /\/api\/v1\/media\/\d+\/thumb/)

    // Resize via the grip's keyboard path: +120 × +80 → 440 × 280
    // (Shift+Arrow = 40 px per step). The grip element sits in the same 16 px
    // corner as the UA's native CSS-resize handle, which intercepts real
    // pointer events there; keyboard drives the identical recordSize/settle
    // → persist path as the pointer drag.
    const grip = page.locator('.rmedia-grip')
    await expect(grip).toBeVisible()
    await grip.focus()
    for (let i = 0; i < 3; i++) await page.keyboard.press('Shift+ArrowRight')
    for (let i = 0; i < 2; i++) await page.keyboard.press('Shift+ArrowDown')

    // Size chip shows the live value immediately.
    await expect(page.locator('.rmedia-size')).toHaveText(/440\s*×\s*280/, {
      timeout: 5000,
    })

    // Settle timer + autosave debounce flush the body to the backend; poll the
    // API rather than guessing the timing.
    await expect
      .poll(
        async () => {
          const r = await request.get(`/api/v1/entries/${entryId}`)
          const entry = await r.json()
          const m = /\?w=(\d+)&h=(\d+)/.exec(entry.body ?? '')
          return m ? `${m[1]}x${m[2]}` : ''
        },
        { timeout: 15000, intervals: [500] },
      )
      .toBe('440x280')

    // Reload: the persisted size comes back identically. (The editor starts on
    // a fresh draft again after reload, so reopen the seeded entry.)
    await page.reload()
    await dismissWhatsNew(page)
    await page.getByText('RESIZE-7 seed').first().click({ timeout: 10000 })
    const previewToggle2 = page.locator('button[title="Preview mode"]')
    await previewToggle2.waitFor({ state: 'visible', timeout: 10000 })
    await previewToggle2.click()
    const wrapper = page.locator('.rmedia')
    await expect(wrapper).toBeVisible({ timeout: 5000 })
    await expect(wrapper).toHaveCSS('width', '440px')
    await expect(wrapper).toHaveCSS('height', '280px')
    // 440 ≤ 640 → still the thumbnail source; the full-size /file must never
    // be fetched by the preview.
    await expect(page.locator('.rmedia img')).toHaveAttribute(
      'src',
      /\/api\/v1\/media\/\d+\/thumb/,
    )
    expect(
      fetched.filter((u) => /\/file(\?|$)/.test(u)),
      'preview must not decode the /file source at ≤640 px',
    ).toEqual([])
  })
})
