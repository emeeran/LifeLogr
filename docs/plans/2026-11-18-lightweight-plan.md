# LifeLogr — lightweight / minimal-resource plan

**Date:** 2026-11-18
**Goal:** reduce RAM, CPU, disk and startup cost **without removing or degrading any
feature**. Every item below keeps the feature surface identical — the work is
lazy-loading, bounding, and proportionality, not cuts.
**Baseline survey:** runtime snapshot + code inventory taken 2026-11-18 (dev env:
Vite ~478 MB, uvicorn ~100 MB + 126 MB reloader, WebKitWebProcess ×2 ≈ 190–215 MB;
disk: sidecar 63 MB, .venv 306 MB, data dir 289 MB).

## Context: what is already light

The heavy-ML leak was closed long ago — torch/scipy/sentence-transformers are
excluded in `desktop/scripts/pyinstaller.spec:140-170`; embeddings are served by
an external Ollama process (nothing model-sized in backend RAM,
`backend/app/services/ollama_service.py:171-192`). Lists are virtualized
(`TimelineView.vue:48-53`, `NotesView.vue:598-608`), routes are code-split
(`frontend/src/router.ts:8-45`), and the ~5 GB renderer OOM was fixed via the
`/thumb` rewrite + `loading="lazy" decoding="async"`
(`frontend/src/utils/markdown.ts:19-56`). The remaining costs are startup work,
bundle overhead, and a handful of unbounded paths.

## Summary

| # | Item | Diagnosis | Size | Risk | Wave |
|---|---|---|---|---|---|
| 1 | PyInstaller one-file → onedir + PIL plugin diet | 63 MB self-extractor decompresses to /tmp on **every** launch; PIL bundles all format plugins | S | Low | 1 |
| 2 | numpy → pure-Python vector math | numpy+BLAS ship solely for one cosine in the semantic cache (`semantic_cache.py:52`) | S | Low | 1 |
| 3 | Rebuild frontend dist | dist (built 09:44) predates the map-removal commit (10:59) — ships dead MapView 192 KB JS + 16.5 KB CSS | S | Low | 1 |
| 4 | Boot work made proportional | full `integrity_check` + full-file snapshot copy (5 retained) + integrity battery are O(DB size) on every boot (`database.py:213-420`, `startup_checks.py`) | M | Medium | 2 |
| 5 | Lazy-load optional stacks | edge-tts (+aiohttp), sounddevice/soundfile (+PortAudio/libsndfile) load into the sidecar even when TTS/recording is never used | M | Medium | 2 |
| 6 | Renderer decode bounds | `MediaViewer.vue` lightbox decodes full files; MediaTimeline decodes a `<video>` frame per item (`:281`); blob-URL revocation unverified; open-entry embedded-image count unbounded | M | Medium | 3 |
| 7 | Semantic-cache RAM ceiling | cache holds every live embedding as float32 forever, unbounded (`semantic_cache.py:1-40`) | S | Low | 3 |
| 8 | Deb dependency slimming | gstreamer bad/good/libav/base + psmisc as hard depends; re-check against WebKit's built-in playback stack | S | Medium | 4 |

**Wave order:** 1 = quick wins (≤1 day total) · 2 = startup cost · 3 = bounded
renderer/cache · 4 = packaging verification. Waves are independently shippable.

---

## 1 — PyInstaller one-file → onedir, PIL plugin diet

### What's there
`desktop/scripts/pyinstaller.spec` builds a one-file EXE (all `a.binaries` +
`a.datas` inside the executable), so every launch decompresses the 63 MB bundle
into /tmp before the backend can bind its port — this doubles startup I/O and
adds launch-latency jitter on top of the existing `main.rs` 30 s TCP probe
(`desktop/src-tauri/src/main.rs:136-146`). PIL is bundled with all format
plugins, but `media_service.py` only exercises WebP (compress/thumbs) and the
JPEG/PNG import paths.

### Change
1. Switch the spec to onedir (`EXE(..., exclude_binaries=True)` + `COLLECT(...)`),
   update the Tauri sidecar path handling and the deb/AppImage packaging to ship
   the directory.
2. Restrict PIL format plugins to WebP/JPEG/PNG/GIF via `Image.init()` filtering
   or excludes in the spec.
3. Measure: record cold-start time and bundle size before/after.

### LW-1.1 status: DEFERRED (2026-11-18) — investigation result

Onedir is **not drop-in** for the current sidecar mechanics. Why:

- Tauri's `externalBin` (`tauri.conf.json:60-62`) expects exactly **one
  executable file per triple**; `desktop/Makefile` and
  `.github/workflows/build.yml` ("Prepare sidecar") copy the single
  `dist/lifelogr-backend` to `src-tauri/lifelogr-backend-<triple>` to match.
- PyInstaller onedir output is `dist/lifelogr-backend/` = small bootloader exe
  **plus an `_internal/` directory** whose location the bootloader hardcodes as
  "next to itself".
- Tauri installs `externalBin` targets to `/usr/bin/` (deb) or `usr/bin/` inside
  the AppImage, while `bundle.resources` land under `/usr/lib/<productName>/` —
  the two are never adjacent, so an onedir exe bundled via `externalBin` cannot
  find `_internal`. Keeping `externalBin` unchanged is therefore impossible
  without relocating the exe.
- `main.rs` spawns through `tauri_plugin_shell`'s `sidecar()` (fixed
  `<exe_dir>/<name>-<triple>` resolution) and its ownership/`classify_port_owner`
  logic keys off the bootloader-pid vs Python-child relationship of the one-file
  layout — all of that shifts in a rework and cannot be verified without a real
  cargo/tauri build, which is out of scope for this pass.

**Safe subset shipped instead:** the PIL plugin diet + numpy exclusion
(LW-1.2) landed in `pyinstaller.spec`; the one-file EXE is unchanged.

**Follow-up steps for the onedir migration** (needs a build-capable session):

1. Spec: add `COLLECT` and `EXE(exclude_binaries=True)`; keep `name='lifelogr-backend'`
   so the output dir is `dist/lifelogr-backend/{lifelogr-backend,_internal/}`.
2. Drop `externalBin` from `tauri.conf.json`; bundle the whole onedir tree as a
   resource instead, e.g. `"resources": {"../dist/lifelogr-backend/**": "backend/"}`.
3. `main.rs`: replace `app.shell().sidecar("lifelogr-backend")` with an explicit
   `std::process::Command` on `app.path().resource_dir()/backend/lifelogr-backend`,
   keeping the existing arg/probe/reclaim/verify logic; track the child with
   `std::process::Child` in `SidecarChild` (swap the `tauri_plugin_shell`
   `CommandChild` type). In onedir the bootloader does **not** fork a Python
   child, so spawned pid == port-owner pid: `classify_port_owner`'s pid-mismatch
   branch becomes a true stale-backend detector (keep the cmdline+PPid check as
   a belt-and-braces).
4. Packaging: deb/AppImage resource paths now carry `_internal/`; verify
   executable-bit preservation through the deb data tarball and the AppImage
   squashfs (PyInstaller marks the bootloader +0; if Tauri's resource copy
   strips it, restore via `preInstallScript`/`postInstallScript`).
5. `desktop/Makefile` + `.github/workflows/build.yml`: replace the single-file
   `cp` ("Prepare sidecar") with copying the whole `dist/lifelogr-backend/`
   directory; the CI health check becomes
   `./desktop/dist/lifelogr-backend/lifelogr-backend --host ... --port ...`.
6. Verify `scripts/close-timing.sh` timings (LW-M2) and the media suite; record
   before/after cold-start + bundle size in this doc (LW-1.3).

### Acceptance criteria
- Desktop app cold-starts noticeably faster; no /tmp extraction step.
- Deb/AppImage still build and install; sidecar ownership + shutdown guards
  (`main.rs`) still pass.
- Media upload/thumb/OCR flows unchanged (pytest media suite green).

## 2 — numpy → pure-Python vector math

> **Status 2026-11-18:** the cache rewrite shipped (see §7), but numpy **stays
> in the bundle**: `services/recording_service.py` requires it for the FFT
> high-pass / spectral-gate / Ogg-encode path, so it cannot become optional
> without a `voice`-extra + feature-detect design decision. The spec's numpy
> exclude was reverted accordingly.

### What's there
numpy (with BLAS) is in the sidecar solely for the embedding-matrix cosine in
`backend/app/services/semantic_cache.py:52`. Journal-scale N×dim products are
microseconds in pure Python.

### Change
1. Replace the numpy matrix ops with pure-Python math (or `array` module).
2. Move numpy to an optional extra; drop it from the PyInstaller bundle.
3. Keep the on-disk cache format readable (float32 via `struct`/`array`) so no
   migration is needed.

### Acceptance criteria
- Hybrid/semantic search returns identical result ordering on the existing test
  fixtures (byte-for-byte score tolerance documented).
- `uv run pytest tests/` green; numpy absent from the rebuilt sidecar.

## 3 — Frontend dist rebuild + dead chunk purge

### What's there
`frontend/dist` predates commit `980f384` (map removal): it still ships
`MapView` 192 KB JS + 16.5 KB CSS that no source references. Largest live
chunks after that: index 170 KB, SettingsView 124 KB, vendor-icons 95 KB,
NotesView 65 KB, vendor-markdown 64 KB, plus a 132 KB memorial JPG and
CHANGELOG/WhatsNew chunks (34 KB + 33 KB).

### Change
1. Rebuild dist; verify the MapView chunk is gone from the bundle manifest.
2. Move the memorial JPG behind a lazy route chunk.
3. Record before/after bundle sizes in this doc.

### Acceptance criteria
- No chunk containing removed route code in `dist/assets/`.
- Playwright e2e suite green.

## 4 — Boot work made proportional

### What's there
Every desktop boot runs, in order (`backend/app/core/database.py:213-420`):
full-DB `PRAGMA integrity_check`, a **full file copy** boot snapshot (5 full
copies retained, `:229-230`), WAL checkpoint, create_all + inline migrations +
FTS5 setup. Then `startup_checks.py` (573 LOC battery: integrity,
fragmentation, backup self-heal) runs in the startup path before the API is
fully ready. All of it is O(DB size) — the dominant boot cost as the journal
grows.

### Change
1. Boot: `PRAGMA quick_check` (O(1)-ish header check) instead of full
   `integrity_check`; promote full `integrity_check` to a weekly APScheduler
   job using the existing corrupt-recovery path.
2. Snapshot rotation: keep 2 recent full copies + 1 per-week; skip the copy
   when the DB's size + page-count are unchanged since the last snapshot.
3. Defer the `check_app_integrity` battery to a post-boot scheduled job
   (e.g. 60 s after listen) so the window paints sooner; surface any finding
   through the existing integrity report UI rather than blocking boot.
4. Keep unchanged: WAL/pragmas (`database.py:51-78`), corrupt-DB
   restore/quarantine, `_migrate_schema`, FTS5 setup, backup catch-up.

### Acceptance criteria
- Cold boot time no longer scales with DB size (measure with a synthetic
  large-DB fixture).
- Corrupt-DB fixture still recovers via the weekly job and on quick_check
  failure.
- All existing integrity/startup tests pass unchanged semantics.

## 5 — Lazy-load optional feature stacks

### What's there
The sidecar always loads edge-tts (+aiohttp) and sounddevice/soundfile
(+PortAudio/libsndfile). Recording is already lazy-imported
(`recording_service.py:161-164`); TTS imports eagerly.

### Change
1. Make `edge_tts` import lazy in `services/tts` / `routers/tts.py` (import on
   first synthesize call; keep the 1000-file/250 MB disk LRU unchanged,
   `tts.py:58-60`).
2. Verify sounddevice/soundfile and their native libs stay out of the startup
   import graph; exclude them from the spec's always-bundle list if PyInstaller
   still links them (lazy imports keep them bundled but unloaded).
3. APScheduler stays (reminders/backups/vacuum/trash need it at boot — this is
   robustness load-bearing).

### Acceptance criteria
- First TTS use and first recording still work in the desktop app.
- Startup import graph (`python -X importtime` or equivalent) no longer
  includes edge_tts/aiohttp.
- Backend RSS at steady idle measurably lower.

## 6 — Renderer decode bounds

### What's there
Three residual unbounded decode paths in the renderer (the OOM-prone process):
- `MediaViewer.vue` lightbox loads the **full file** for any size.
- `MediaTimelineView.vue:281` renders real video first-frame thumbnails via
  muted `<video>` elements — each decodes in the renderer; count is
  page-bounded (50) but decode cost is per-video.
- Open entry/note editor renders every embedded image in one DOM (thumb-capped
  at 640 px, but count-unbounded).
- Blob URLs via `URL.createObjectURL` (`api/tts.ts:37`, `NoteEditor.vue:723`,
  `markdownMedia.ts:136`) — revocation unverified; leaks accumulate over a
  long session.

### Change
1. MediaViewer: serve `/thumb` upscaled for sizes ≤ 2× viewport; fetch
   full-res only on zoom-to-100 % / download.
2. MediaTimeline: video first-frame thumbs for the first ~12 visible items;
   static placeholder icon beyond that until scrolled into view.
3. Audit + revoke every `createObjectURL` on component unmount / player stop.
4. Cap concurrently-mounted embedded images per open editor (IntersectionObserver
   placeholder swap above ~20 images), consistent with the existing
   `loading="lazy"` pipeline.

### Acceptance criteria
- Open a 100-image entry + media timeline in the desktop app: renderer RSS
  plateaus (record numbers) instead of growing linearly.
- Lightbox still shows full-res on zoom; TTS audio and voice-note playback
  unaffected.
- New vitest coverage for the blob-URL revocation helper.

## 7 — Semantic-cache RAM ceiling

### What's there
`SemanticSearchCache` holds every live entry+note embedding as float32 matrices
in RAM indefinitely (`semantic_cache.py:1-40,221-227`) — ~30 MB × 2 at 10k
entries × 768 dim, growing without bound.

### Change
1. Store embeddings as float16 (halves RAM; cosine precision loss is
   negligible for ranking) or segment the matrix with an LRU on segments.
2. Keep the divergence-count reload check intact.

### Acceptance criteria
- Search ranking unchanged on fixtures (top-k identical).
- Cache RSS bounded and asserted in a unit test.

## 8 — Deb dependency slimming (verify-heavy, last)

### What's there
The deb hard-depends on gstreamer plugins-base/good/libav/bad, tesseract,
portaudio, psmisc. psmisc (`fuser`/`pkill`) is only for port-squat reclaim in
`main.rs`; the gstreamer set backs video playback in WebKit.

### Change
1. Test video/voice-note playback with only plugins-base + good; drop
   libav/bad if WebKit's built-in stack covers the shipped formats (WebM/MP4
   matrix — verify manually per format).
2. Make psmisc a Recommends and degrade gracefully in `main.rs` when missing.

### Acceptance criteria
- Playback matrix documented (format × works/fails) on a clean install of the
  slim deb.
- Port-squat recovery still works with psmisc absent (fallback path tested).

---

## Guardrails — do NOT touch

These are load-bearing per the 2026-10 media-loss and OOM incident history:

- WAL + pragmas and DB boot-bak restore/quarantine (`core/database.py`)
- Trash retention sweep + purge-only-in-`EntryService.purge` semantics
- Backup catch-up (45 s post-boot) and `SchedulerService.sync_reminders()`
- Shutdown-guard trio in `main.rs` (SIGTERM → 2.5 s → SIGKILL)
- Unlink-media-only-after-commit rule for any new delete path
- Egress warnings and origin-trust checks

Wave 2's changes reduce the *frequency* of integrity work, never the coverage:
full `integrity_check` still runs weekly and on any `quick_check` failure.
