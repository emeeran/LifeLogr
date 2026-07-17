import { test, expect } from '@playwright/test'

/**
 * Real integration smoke — drives the *running backend* through the Vite /api
 * proxy. Unlike the settings UI specs (which assert static labels and stay
 * green even against a dead or entirely wrong backend), this creates an entry
 * and proves the FTS5 index picks it up on a subsequent search. A
 * misconfigured, broken, or wrong backend therefore fails the suite.
 *
 * All paths are relative to baseURL (the Vite dev server), which proxies
 * /api → the backend port, so the request traverses the same path the app uses.
 */
test('create entry → full-text search finds it via the real backend', async ({
  request,
}) => {
  // A single alphanumeric token survives FTS5 tokenization and query parsing
  // unchanged, keeping the search round-trip deterministic (no query operators).
  const token = `e2esmoke${Date.now()}`

  const created = await request.post('/api/v1/entries', {
    data: {
      entry_date: '2026-07-14',
      title: 'E2E integration smoke',
      body: `looking for the unique marker ${token} in the index`,
    },
  })
  expect(created.ok(), `POST /entries → ${created.status()}`).toBeTruthy()
  const { id } = await created.json()

  try {
    const search = await request.get(
      `/api/v1/entries/search?q=${encodeURIComponent(token)}`,
    )
    expect(search.ok(), `GET /entries/search → ${search.status()}`).toBeTruthy()
    const results = await search.json()
    const hit = (results.items ?? []).some((e: { id: number }) => e.id === id)
    expect(hit, 'created entry must appear in search results').toBeTruthy()
  } finally {
    // Leave the throwaway DB clean whether the assertion passed or failed.
    await request.delete(`/api/v1/entries/${id}`)
  }
})
