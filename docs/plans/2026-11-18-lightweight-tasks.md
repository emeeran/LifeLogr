# LifeLogr — lightweight / minimal-resource tasks

**Date:** 2026-11-18
**Plan:** `docs/plans/2026-11-18-lightweight-plan.md`
**Rule:** every task must preserve the full feature surface — see the plan's
Guardrails section before touching boot, backup, or shutdown code.

## Wave 1 — quick wins

- [ ] **LW-1.1** Switch `desktop/scripts/pyinstaller.spec` from one-file to
      onedir; update sidecar path handling in `main.rs` and deb/AppImage
      packaging accordingly. *(DEFERRED — onedir breaks the Tauri `externalBin`
      single-file contract: the PyInstaller `_internal/` dir cannot be installed
      next to the exe in deb/AppImage layouts. Safe subset shipped (LW-1.2);
      full migration steps written up in plan §1 "LW-1.1 status: DEFERRED".)*
- [x] **LW-1.2** Restrict bundled PIL format plugins to WebP/JPEG/PNG/GIF.
      *(Done in `pyinstaller.spec` excludes — kept set is actually
      PNG/JPEG/WebP/BMP/TIFF + GIF/MPO, because `media_service._CONVERTIBLE_IMAGE_TYPES`
      explicitly accepts BMP and TIFF; also drops ImageCms/ImageFont so
      littlecms/freetype native libs leave the bundle. Needs one real
      PyInstaller build to confirm size + media suite.)*
- [ ] **LW-1.3** Record cold-start time + bundle size before/after LW-1.1
      (append to the plan doc).
- [ ] **LW-2.1** Replace the numpy matrix cosine in
      `backend/app/services/semantic_cache.py` with pure-Python math; make
      numpy optional and drop it from the PyInstaller bundle.
      *(Partial: semantic_cache.py rewritten pure-Python float16 (done, LW-7.1),
      but numpy CANNOT go optional — `services/recording_service.py` requires it
      for the FFT denoise/high-pass/Ogg-encode path. Needs a decision: optional
      `voice` extra + feature-detect, or keep numpy required.)*
- [ ] **LW-2.2** Test: semantic/hybrid search top-k identical on existing
      fixtures; numpy absent from rebuilt sidecar.
      *(Top-k parity test done in `test_semantic_cache.py`; sidecar part blocked
      on LW-2.1's packaging decision.)*
- [x] **LW-3.1** Rebuild `frontend/dist`; verify no MapView chunk in
      `dist/assets/`; lazy-route the memorial JPG; record bundle sizes.
      *(Done: rebuilt 2026-11-18 — no Map* chunk in `dist/assets/`; dist total
      1.4 MB → 1.2 MB (41 JS chunks). The memorial JPG is a hashed asset of the
      lazy `DedicationTab` chunk, so it only fetches when that tab renders.
      Largest chunks: index 170 KB, SettingsView 124 KB, vendor-icons 95 KB,
      NotesView 65 KB, vendor-markdown 64 KB.)*

## Wave 2 — startup cost

- [x] **LW-4.1** Boot path: full `integrity_check` → `quick_check`; move the
      full check to a weekly APScheduler job reusing the corrupt-recovery path
      (`core/database.py`).
      *Done: `_preflight_db_file_sync` + `validate_db_health` run `quick_check`
      with escalation to the full check on failure; weekly job
      `full_integrity_check` (Sun 04:00) registered via
      `SchedulerService.register_weekly_integrity_check`, recovering through
      `_recover_from_snapshot_sync` + `reinit_engine`.*
- [x] **LW-4.2** Snapshot rotation: 2 recent full + 1 per-week; skip the copy
      when DB size/page-count is unchanged since the last snapshot.
      *Done: `_rotate_boot_snapshots` (2 recent + newest per earlier ISO week,
      `-wal`/`-shm` sidecars filtered from the glob); skip via
      `_db_fingerprint_sync` (size+page_count, immutable read after a
      checkpoint).*
- [x] **LW-4.3** Defer the `check_app_integrity` battery
      (`core/startup_checks.py`) to a ~60 s post-boot job; findings surface via
      the existing integrity report, boot never blocks.
      *Done: `SchedulerService.schedule_app_integrity_check` one-shot
      (`app_integrity_deferred`); `main.py` runs it inline only as a fallback
      when the scheduler couldn't start.*
- [x] **LW-4.4** Test: synthetic large-DB fixture shows boot time independent
      of DB size; corrupt-DB fixture still recovers.
      *Done via logic units (a wall-clock large-DB fixture is too noisy for CI):
      healthy DB → full check never runs at boot; unchanged DB → no new
      snapshot; corrupt-DB fixture still recovers via the unchanged recovery
      path; weekly job healthy/corrupt/no-snapshot cases.*
- [x] **LW-5.1** Lazy-import `edge_tts` (+aiohttp chain) in the TTS service on
      first synthesize; disk LRU caps unchanged.
      *Found already lazy (function-local imports in `routers/tts.py`); added
      `tests/unit/test_tts_lazy_import.py` asserting edge_tts absent at startup
      and present only after a synthesize call. LRU caps (1000 files / 250 MB)
      untouched.*
- [x] **LW-5.2** Verify sounddevice/soundfile/PortAudio stay out of the startup
      import graph; measure idle backend RSS before/after (record in plan doc).
      *Verified lazy (function-local in `recording_service.py`) and enforced by
      the new test. Idle RSS after full `app.main` import: ~88 MB with none of
      edge_tts/aiohttp/sounddevice/soundfile loaded — no before/after delta to
      record since edge_tts was already lazy before this wave.*

## Wave 3 — bounded renderer + cache

- [x] **LW-6.1** MediaViewer lightbox: `/thumb` for ≤ 2× viewport; full-res
      only on zoom-to-100 % / download.
- [x] **LW-6.2** MediaTimeline: video first-frame thumbs for the first ~12
      visible items, placeholder beyond until scrolled into view.
- [x] **LW-6.3** Audit all `URL.createObjectURL` sites (`api/tts.ts`,
      `NoteEditor.vue`, `markdownMedia.ts`) and revoke on unmount/stop; add a
      shared helper + vitest coverage.
- [x] **LW-6.4** Cap concurrently-mounted embedded images per open editor
      (~20, IntersectionObserver placeholders).
- [ ] **LW-6.5** Manual: 100-image entry + media timeline in the desktop app —
      renderer RSS plateaus; lightbox zoom still full-res; TTS/voice playback
      unaffected.
- [x] **LW-7.1** Semantic cache: float16 storage (or segmented LRU); keep the
      divergence-reload check; unit test asserting bounded RSS and unchanged
      top-k.
      *(Done: float16 row-major blob storage + pure-Python cosine in
      `semantic_cache.py`; divergence check untouched; tests cover packed size,
      top-k parity vs the legacy float32 math, and self-heal reload.)*

## Wave 4 — packaging verification

- [ ] **LW-8.1** Playback matrix on clean install: video/voice-note formats ×
      {plugins-base+good only, current set}; drop libav/bad only if the slim
      set covers every shipped format.
- [x] **LW-8.2** psmisc → Recommends; graceful degrade + fallback test for
      port-squat recovery in `main.rs` when it's absent. *(Done: `tauri.conf.json`
      deb `recommends`; `reclaim_port` now tries fuser → pkill → lsof+signals →
      clear GiveUp message, with the decision core `reclaim_strategy` unit-tested
      (4 tests green via `cargo test reclaim`). Clean-install verification of the
      Recommends-only install still recommended before release.)*

## Manual / desktop-GUI acceptance (after all waves)

- [ ] **LW-M1** Full feature sweep in the real desktop app: entry CRUD + tags,
      notes + folders + inline tags, OCR, TTS read-aloud, recording, AI tools,
      search (keyword + semantic + hybrid), backup restore, encryption
      round-trip, export, Diarium import, reminders + catch-up.
- [ ] **LW-M2** Verify shutdown timings still meet the §9 targets
      (`scripts/close-timing.sh`) after LW-1.1 and LW-4.x.
