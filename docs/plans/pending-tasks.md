# LifeLogr — pending tasks

Exported 2026-11-07 from `docs/plans/2026-11-07-modify-idea-tasks.md` (the
full plan; IDs and decision context live there). Everything below is what
remains open after the security wave landed in `4079fe9` and `3f2ee5f`.

## Needs the real desktop GUI

- [ ] **MIC-6** Manual width check of the mic-in-bottom-bar at 380 px, 720 px and
      fullscreen: no overlap with the editor body.
- [ ] **CLOSE-6** Verify shutdown timings on a real desktop run against the §9
      targets. Use `scripts/close-timing.sh`; `scripts/snip-smoke.sh` covers the
      related capture checklist.
- [ ] **SEC (design §12, manual acceptance)** On a copy of the data dir: run the
      Migration "Encrypt attachments of encrypted items", then a `strings`-on-media
      check shows no decodable image for encrypted items' attachments or thumbs.

## Deferred by design

- [ ] **BLANK-7** Renderer heartbeat (5 s `/health`, two missed beats → reload
      overlay). A crashed/killed renderer cannot detect itself — the honest fix
      is a native watchdog in the Tauri shell; needs its own small design.

## Needs new infrastructure (Playwright e2e harness)

Both blocked on the same prerequisite: install Playwright + browsers and a way
to boot the stack for tests. Build the harness once, then both specs are small.

- [ ] **BLANK-8** `tests/e2e/blank-screen.spec.ts` — a throwing view renders the
      ErrorBoundary (reload + copy details), not a blank page.
- [ ] **RESIZE-7** Paste → drag grip → reload → size identical (`?w=&h=` persisted);
      downsize to 320 px decodes only the `/thumb` source.

## Feature-sized (start fresh)

- [ ] **DND-3 (remainder)** Between-row insertion line for drag-reordering in the
      notes rail. Notes have no `sort_order` column (inline migration in
      `core/database.py:_migrate_schema`); folder reordering needs N sequential
      PATCHes unless a batch endpoint is added. Already done: drop onto Unfiled /
      Notebooks header un-files / moves to top level.
- [ ] **SEC-MEDIA-7 follow-ups** (only if wanted): Markdown export frontmatter for
      encrypted entries currently notes the omission; HTML/PDF could surface a
      similar note inline. Low priority.

## Process

- [ ] **DEC-5** Create one issue per wave on `emeeran/LifeLogr`, each linking
      `docs/plans/2026-11-07-modify-idea-tasks.md`. (Awaiting go-ahead; not yet
      opened.)

## Not tracked as tasks (done or resolved)

Waves 0–3 and the SEC-* wave are otherwise complete — see the checked items and
the decisions log in `2026-11-07-modify-idea-tasks.md`, plus
`docs/plans/2026-11-07-modify-idea-plan.md` for rationale.

Known unrelated debt (not part of this plan): `tests/unit/test_main_misc.py::
TestSpaCatchAll` — 2 failures introduced by the `e0204e5` stability commit
(SPA catch-all returns 404 for client routes); pre-dates the security wave and
needs a separate fix.
