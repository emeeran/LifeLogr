# LifeLogr — Diarium-Inspired Implementation Tasks

**Date:** 2026-10-25
**Companions:** [diarium-enhancement-ideas.md](diarium-enhancement-ideas.md)
(the "what" and rationale) ·
[diarium-format-analysis.md](diarium-format-analysis.md) (file-format ground
truth) · [roadmap-2026-10-24.md](roadmap-2026-10-24.md) (pre-existing backlog
— see Dependencies below).

Task IDs are `D#` to avoid colliding with the roadmap's numbered items.
Effort: **S** ≤ 1 day, **M** 1–3 days, **L** > 3 days. Every task ends with
`ruff` + `pytest` green and, for UI tasks, vitest for new components.

---

## Dependencies to know before starting

- **Roadmap P1#5 (bulk import batching)** — the Diarium import route commits
  per entry and fans out uncapped AI enrichment. D2/D3 add more per-entry
  data to import; do the batching first or together, or large imports get
  worse.
- **Roadmap P1#7 (schema-upgrade test coverage)** — D2/D3 add columns/tables;
  `init_db`'s `_drop_removed_feature_tables` behavior is currently untested.
  Cover the upgrade path before migrating schema, not after.
- **Fixtures** — tests need a *synthetic* `.diary` builder (tiny SQLite with
  the documented schema) so suites never touch the real 190 MB personal
  backup, and so unobserved enum values (`Tags.Type=2`, `Events.Type≠0`,
  `Media.Type=2`) can be exercised. Build once in conftest, reuse in D2–D4.

---

## Tier 1

### D1 — Map view for geotagged entries · **L**
- **Why:** coordinates are imported (`models/entry.py`, 930/1,393 entries in
  the reference backup) but no frontend code reads them.
- **Backend:** `GET /api/v1/entries/geotags` — id, date, lat, lng, title,
  thumbnail ref for entries with non-zero coordinates; paginate.
- **Frontend:** new `/map` route + `components/map/MapView.vue`; marker
  clustering; click → entry detail.
- **Privacy decision (block first):** tile source. OSM tile servers see the
  viewed area (and possibly inferred home location). Options: (a) opt-in
  online tiles listed in the Settings → Privacy egress report, (b) offline
  vector-tile pack for the user's region, (c) plot-only mode (no basemap).
  Default conservative; document the choice in the egress table either way.
- **Accept:** markers render for all geotagged entries; zero tile requests in
  default config (verified by a client-interceptor test); route + API
  covered by vitest/pytest.

### D2 — Import Diarium Events (weather) · **M**
- **Why:** importer skips the `Events` table; weather is the one verified
  event type (`Type=0`, `"84 / 74 °F"` + condition in `Tag`).
- **Schema:** new `entry_events` table (entry_id, kind, content, label) —
  not a JSON column, so FTS/future charting stays queryable.
- **Importer:** in `importers/diarium.py`, map `Events.Type=0` → weather;
  carry unknown types as `kind="unknown:<n>"` rather than dropping (the
  enum is unverified beyond 0). Log counts per type.
- **UI:** weather context line in `EntryDetail.vue` / `EntryHeader.vue`.
- **Accept:** synthetic `.diary` fixture with all observed + an unobserved
  event type imports losslessly; unknown types survive round-trip export;
  schema-upgrade test added per the dependency note.

### D3 — Tag trackers (Tags.Type=2 + TrackingValue) · **M**
- **Why:** vendor-confirmed feature ("track mood, weight or other metrics");
  lifelogr's mood is a single 1–5 field. Not present in the reference backup
  — fixture-driven only.
- **Schema:** tracker definition on tags + per-entry value table (or JSON
  column on the entry-tag association — decide during design; values observed
  in the wild are strings of unknown shape, so store verbatim and parse at
  read time).
- **Importer:** map `Tags.Type=2` → tracker; `TrackingValue` verbatim.
  Existing guard (`Type IN (0,1)`) extends to 2.
- **UI:** read-only first — show tracker values on the entry; charting is a
  follow-up once real-world value shapes are known (don't guess a parser).
- **Accept:** fixture with trackers imports; entries display values; no
  regression in the tag-import path (existing tests stay green).

### D4 — "On this day" · **S**
- **Why:** pure query over existing data; highest nostalgia-per-line-of-code.
- **Backend:** `GET /api/v1/entries/on-this-day` → entries from prior years
  matching today's date (excluding year 1 artifacts; handle leap day).
- **Frontend:** card on the calendar view (default route) + optional daily
  reminder body extension (`routers/reminders.py` already has desktop
  notifications).
- **Accept:** endpoint test covering same-date-multi-year, empty, and leap-day
  cases; reminder notification includes the entry count.

## Tier 2

### D5 — Journaling statistics dashboard · **M**
- **Backend:** aggregate endpoint — streak (consecutive days with entries),
  total words (FTS5 lengths), entries/week histogram, mood distribution,
  media counts. One query pass, cache in memory.
- **Frontend:** `/stats` route; charts (existing chart lib or minimal SVG —
  keep bundle lean).
- **Accept:** aggregates verified against a seeded DB in unit tests; empty
  journal renders zeros, not an error.

### D6 — Daily word-count goal · **S**
- **Settings** field (default off); today's count shown in
  `EditorStatusBar.vue`; colored once the goal is met. Counts derive from the
  same word-length helper as D5 — write it once.
- **Accept:** goal stored in settings; status bar updates on debounce; zero
  network.

### D7 — Weather auto-fill for geotagged entries · **M**
- **Opt-in** setting (off by default — this is the one feature whose network
  call is tied to location data). Provider: Open-Meteo (no key, no account)
  rather than Diarium's Apple Weather.
- **Flow:** on entry save with coordinates, fetch + cache daily conditions
  (reuse the TTS disk-cache pattern); backfill is explicitly out of scope for
  v1 (history queries are a premium API there).
- **Privacy:** add a row to the Settings → Privacy egress report; never send
  entry text, only lat/long rounded (≤2 decimals ≈ 1 km) to the weather API.
- **Accept:** egress report lists the surface; rounding covered by test; app
  fully functional with the feature off.

## Tier 3

### D8 — Migration importers: Day One JSON, Daylio CSV · **M each**
- Extend the `importers/` package pattern (Diarium JSON parser is the
  template: pure function, dict-in → import-shaped dict-out, unit-tested).
- Day One: JSON export with photos in a sidecar zip — media re-attachment
  mirrors the Diarium SQLite path.
- Daylio: CSV (entries, moods, activities); map mood icon names to the
  awful→great scale.
- **Accept:** golden-file fixtures per format; both feed the same import
  pipeline (and therefore inherit the D2-era batching fix).

### D9 — Export .docx / .html · **M**
- Extend `services/export_service.py` (which already produces archive /
  `.diary` / Markdown ZIP with media). HTML export is close to the Markdown
  path; .docx needs a writer lib — evaluate `python-docx` weight vs. shipping
  HTML only first.
- **Accept:** round-trip spot check against a seeded DB; media referenced
  relatively like the Markdown ZIP path.

### D10 — Entry-composer context sidebar · **L**
- Camera-roll: list files by date from a user-chosen directory; system
  calendar: read-only ICS from a user-chosen path (Linux: Evolution dir) —
  both **local-only**, nothing persisted unless attached, mirroring Diarium's
  model.
- Gated behind opt-in settings; adds no network surface.
- **Accept:** with feature off, zero filesystem scanning occurs; attached
  items land in the normal media pipeline.

### D11 — Feed integrations (GitHub, Last.fm, …) · **deferred**
- Deliberately last: OAuth surface + narrow audience. Revisit after D1–D7
  land; the `entry_events` table from D2 is the natural storage.

## Explicitly out of scope (unchanged from the ideas doc)

Shared journals, Diarium-style encrypted sync payloads, biometric app lock —
rationale in [diarium-enhancement-ideas.md](diarium-enhancement-ideas.md).

## Suggested sequencing

```
D4 (S) → D6 (S) → D5 (M)        quick wins, no schema changes
D2 (M) → D3 (M)                 schema work after roadmap P1#5/#7 land
D1 (L)                          after the tile-privacy decision
D7 (M) → D8 → D9 → D10 → D11    ecosystem, one at a time
```
