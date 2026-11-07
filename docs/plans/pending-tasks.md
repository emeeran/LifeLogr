# LifeLogr — pending tasks

Updated 2026-11-07 after the batch on the `feature/pending-tasks-batch`
branch (DND-3 remainder, SEC-MEDIA-7 export notes, BLANK-8 + RESIZE-7 e2e,
DEC-5 issues). IDs and decision context live in
`docs/plans/2026-11-07-modify-idea-tasks.md`; per-wave tracking now also
lives in issues #19–#22 on `emeeran/LifeLogr`.

## Needs the real desktop GUI (manual)

- [ ] **MIC-6** Manual width check of the mic-in-bottom-bar at 380 px, 720 px and
      fullscreen: no overlap with the editor body. (#19)
- [ ] **CLOSE-6** Verify shutdown timings on a real desktop run against the §9
      targets. Use `scripts/close-timing.sh`; `scripts/snip-smoke.sh` covers the
      related capture checklist. (#20)
- [ ] **SEC (design §12, manual acceptance)** On a copy of the data dir: run the
      Migration "Encrypt attachments of encrypted items", then a `strings`-on-media
      check shows no decodable image for encrypted items' attachments or thumbs. (#22)
- [ ] **Wave-3 manual pass** Move 10 notes and 3 notebooks in a real session
      without losing one; check the resize grip's **pointer** path on WebKitGTK —
      the grip shares its corner with the UA's native CSS-resize handle, which
      intercepts real pointer events in Chromium (the keyboard path works; if
      WebKit behaves the same, move the grip inward). (#21)

## Deferred by design

- [ ] **BLANK-7** Renderer heartbeat (5 s `/health`, two missed beats → reload
      overlay). A crashed/killed renderer cannot detect itself — the honest fix
      is a native watchdog in the Tauri shell; needs its own small design. (#20)

## Known unrelated debt

- `tests/unit/test_main_misc.py::TestSpaCatchAll` — 2 failures introduced by the
  `e0204e5` stability commit (SPA catch-all returns 404 for client routes);
  pre-dates the security wave and needs a separate fix.
- `tests/settings.spec.ts` "Data tab" e2e fails in this environment (Export
  button never appears) on the unmodified baseline too — needs triage with the
  dev stack, possibly an overlay/timing issue rather than a regression.

## Done in this batch (was open in the previous export)

- **DND-3 remainder** — `notes.sort_order` (inline migration, `_SCHEMA_VERSION`
  4), batch `POST /notes/reorder` + `POST /notes/folders/reorder`, between-row
  insertion line in the rail; never-reordered sections keep recent-first.
- **SEC-MEDIA-7 follow-ups** — HTML/PDF exports note the omitted attachments of
  encrypted entries inline (one shared sentence with the Markdown frontmatter).
- **BLANK-8 + RESIZE-7** — e2e specs in `frontend/tests/`, in CI. RESIZE-7
  caught a real bug: the `/thumb` rewrite dropped `?w=&h=`, so resizing a
  downsized image never persisted (fixed; CHANGELOG under Fixed).
- **DEC-5** — one issue per wave: #19 (Wave 1), #20 (Wave 2), #21 (Wave 3),
  #22 (Wave 4), each linking the plan doc.
