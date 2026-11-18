# LifeLogr — pending tasks

Updated 2026-11-18. Older per-wave detail (2026-11-07/08 modify-idea waves)
has been pruned; closed work lives in CHANGELOG.md, and the current active
wave is `docs/plans/2026-11-18-lightweight-tasks.md`.

## Needs the real desktop GUI (manual)

- [ ] **MIC-6** Manual width check of the mic-in-bottom-bar at 380 px, 720 px and
      fullscreen: no overlap with the editor body. (#19)
- [ ] **CLOSE-6** Verify shutdown timings on a real desktop run against the §9
      targets. Use `scripts/close-timing.sh`; `scripts/snip-smoke.sh` covers the
      related capture checklist. (#20) — re-run after the lightweight pass.
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
