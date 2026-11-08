# LifeLogr — `modify-idea.md` implementation plan

**Date:** 2026-11-07
**Source list:** `docs/modify-idea.md`
**Method:** every item was traced to code before planning. Where the capability already
exists, the plan starts with a repro instead of a rebuild — three of the nine items turned out
to be partially or fully implemented, and one ("sniper fail") is a **Wayland screen-capture**
failure, not a Notes bug.

## Summary

| # | Item (as written) | Actual diagnosis | Size | Risk | Wave |
|---|---|---|---|---|---|
| 1 | Distinct colours for the Notes tab | `Note.color` / `NoteFolder.color` exist in DB + API but **no UI reads them** | S | Low | 1 |
| 2 | Resize pasted images (notes + journal) | Resizing **exists** (`useResizableMedia`, `.rmedia { resize: both }`) for preview-rendered media; needs repro to find the real gap (discoverability, full-res decode, `<video>` blocks) | S–M | Low | 3 |
| 3 | Move floating mic next to the speaker | Mic is a fixed FAB at `bottom-20 right-4`; TTS speaker lives in the bottom toolbar | S | Low | 1 |
| 4 | Ensure data safety and security | Media files are **plaintext at rest** even for encrypted entries; backups have **no checksum manifest**; no key-recovery kit | L | Medium | 4 |
| 5 | "Sniper fail in Notes" | → **"Screen capture failed: Cannot find required wayland protocol"** — `xcap` needs `zwlr_screencopy`, which GNOME does not implement; the portal is available and unused | M | Medium | 2 |
| 6 | Notes draggable, droppable, nestable | Nesting (`parent_id` + cycle guard), sub-notebook creation and move-via-dropdown **already work**; only **drag-and-drop** is missing | M | Low | 3 |
| 7 | Auto-title from first line | Not implemented anywhere (no `autoTitle`/`firstLine` code) | S | Low | 1 |
| 8 | Screen frequently goes blank | No global Vue error handler / `unhandledrejection`; markdown previews decode **full-resolution** images with no `loading`/`decoding` attributes and never use the existing `/thumb` endpoint → WebKitWebProcess OOM (already documented as ~5 GB in `AUDIT.md`) | M–L | Medium | 2 |
| 9 | Slow to close | Tauri's `ExitRequested` handler **blocks the event loop** for up to 5 s polling the port, then falls back to `pkill -f`; backend teardown calls APScheduler `shutdown()` with default wait | M | Medium | 2 |

**Wave order:** 1 = quick UX wins · 2 = stability (blank screen, close, capture) · 3 = notes
interaction · 4 = security hardening. Each wave is independently shippable.

---

## 1 — Distinct colours for the Notes tab

### What's there
- `backend/app/models/note.py:43` (`NoteFolder.color`) and `:78` (`Note.color`) — `String(20)`.
- Read/written by the API: `routers/notes.py:65,81,103`; accepted by `NoteCreate`/`NoteUpdate`/
  `NoteFolderCreate`/`NoteFolderUpdate` (`schemas/note.py:15,25,54,83`).
- The Notes tree (`components/notes/NotesView.vue`) renders folders, sub-folders and notes but
  **never reads `.color`** — grep finds only a `color: null` test fixture.
- The note editor has a folder `<select>` (`NoteEditor.vue:1233`) but no colour affordance.

### Gap
The data model and API are done; the feature is entirely missing in the UI. "Distinct colours
for the Notes tab" is read here as **per-notebook / per-note colour labels in the tree**, with a
secondary option of a Notes-specific accent in the nav (see "Decisions").

### Proposed change
1. `frontend/src/utils/noteColors.ts` — one palette of 8 named tokens (e.g. `slate`, `rose`,
   `amber`, `emerald`, `sky`, `violet`, `lime`, `fuchsia`) with light/dark CSS values and a
   `contrastRatio()` helper. Values are tokens, not arbitrary hex, so themes stay coherent.
2. Tree rows: a 3 px left stripe (folders) / dot (notes) in the chosen colour; a note without
   its own colour inherits the folder's; tooltip carries the colour **name** so colour is never
   the only signal. Selected row keeps the accent ring.
3. Picker: a swatch popover in the folder header (rename/delete row) and in the note editor
   header, calling the existing `store.updateFolder` / `store.updateNote({ color })`. Include a
   "None" entry.
4. Docs: add colour to the Notes section of `USER_MANUAL.md`.

### Acceptance criteria
- Setting a colour on a notebook tints its stripe and its unfiled-by-colour notes; survives
  reload, export and backup (it is a DB column already).
- Colours are distinguishable in both themes (contrast helper tested at ≥ 3:1 for the stripe
  against surface).
- `NotesView.mount.test.ts` asserts a row carries `data-color` and an aria-label naming it.

### Risks
Low. Additive UI over existing columns; no migration.

---

## 2 — Resize pasted images (notes + journal)

### What's there
- `composables/useResizableMedia.ts` — wraps every `img`/`video` in a `.rmedia` span, reads a
  size encoded as `?w=&h=` on the media URL, persists drags by rewriting the body URL through
  `onResize`, and keeps a localStorage fallback.
- `styles/main.css:208` — `.rmedia { resize: both; overflow: hidden; max-width: 100% }` (the CSS
  resize affordance is the handle).
- Both editors wire it: `EntryEditor.vue:621-653`, `NoteEditor.vue:863-963`, re-running on every
  preview render.
- Paste inserts `![name](url)` and **flips preview on** (`EntryEditor.vue:1045`, `NoteEditor.vue:547`),
  so the handle should appear immediately.

### Gap (needs a 30-minute repro before coding)
The capability exists, so the user's request implies one of:
1. **Discoverability** — the CSS resize corner is nearly invisible in WebKit, and it only exists
   in preview mode (default mode is edit/source).
2. **`<video>`/`<audio>` HTML blocks** are inserted as raw HTML (not markdown images) and are not
   resized by the `?w=&h=` path.
3. **Large pasted screenshots never shrink in memory** — the wrapper CSS-scales a full-resolution
   decode (see item 8), so "resizing" does not make a 4 K screenshot cheaper or sharper.

### Proposed change
1. Repro first (Playwright/PoC): paste a PNG in journal and note editors, drag the corner, assert
   the body gains `?w=&h=` and survives reload. Record which of the three causes is real.
2. Always render an explicit handle: a 12 px corner grip plus a floating chip (`W × H`) on
   hover/focus, replacing the bare CSS corner. Add `Alt`+arrow keyboard resize (±20 px) and
   `Shift` for aspect-lock so the feature is reachable without a mouse drag.
3. Persist for `<video>` too by normalising pasted HTML blocks to a markdown/HTML pair that
   `useResizableMedia` already wraps, with `?w=&h=` on the `src`.
4. Cap the *initial* insert at `min(intrinsic, 480 px)` wide so a pasted 4 K screenshot does not
   arrive at full width (the user can grow it).
5. Serve the preview from `/media/{id}/thumb` until an explicit size exists (shared with item 8).

### Acceptance criteria
- Pasting an image in either editor yields a visible handle; dragging it rewrites `?w=&h=` in the
  body, and the size is identical after reload and after export→import.
- Resizing down to 320 px does not decode the full-resolution image in preview (network/decoder
  assertion in the Playwright test).
- `useResizableMedia` gains unit tests for: encoded size wins over legacy localStorage, no write
  without a drag, min-size clamp.

### Risks
Low–medium: touching a shared composable used by both editors; covered by existing mount tests
plus new ones.

---

## 3 — Move the floating microphone next to the speaker

### What's there
- `components/recordings/FloatingRecorder.vue:109` — root is
  `absolute bottom-20 right-4 z-30` (a FAB above the editor), containing the record button and
  the recording pill.
- The TTS "speaker" button is in the bottom toolbar: `EntryEditor.vue:1800-1815` (`Volume2`).
- `FloatingPlayback.vue` is a sibling floating player (`EntryEditor.vue:1945`).

### Gap
Pure layout/placement. The mic is a floating island rather than a toolbar control, so it drifts
from the editor's action cluster and overlaps content on short windows.

### Proposed change
1. Render the **mic trigger** inside the bottom toolbar, immediately left of the TTS button, using
   the same `p-1` icon-button styling (danger tint while recording, spinner while saving).
2. Keep the **recording pill** (meter, timer, Stop) as a popover anchored to that button
   (`absolute bottom-full` above the toolbar) rather than a corner FAB; reuse the existing
   transitions.
3. Move `FloatingPlayback` into the same bottom dock so "speak" and "record/play" share one strip.
4. Keep the `FloatingRecorder` component as the pill host so `useRecordings` and the metering
   canvas are untouched; only its wrapper and the trigger move.
5. Focus mode (`focusMode`) currently hides the recorder — keep that, but the toolbar mic should
   show there too (recording while focused is desirable).

### Acceptance criteria
- Mic button sits adjacent to the speaker button at every window width ≥ 380 px, never
  overlapping the editor body; `aria-label` is `Record voice memo` / `Stop recording`.
- Recording pill appears above the button and does not cover the Save button.
- `EntryEditor` mount test asserts the two buttons are siblings in the bottom toolbar.

### Risks
Low. No backend/state changes.

---

## 4 — Ensure data safety and security

### What's there (verified)
- Per-item encryption for entry/note **text** (`Entry.is_encrypted`, `Note.is_encrypted`).
- Loopback-only binding, CSRF/origin guard chain, optional `API_TOKEN` (`main.py`,
  `AUDIT.md` resolution log).
- Boot-time DB backups + integrity check (`core/database.py`), nightly/cloud backup service,
  tar path-traversal validation, soft-delete now unlinks media **after** commit.
- `test_backup_roundtrip.py` proves export → wipe → restore is byte-identical for entries, media,
  notes and attachments.

### Gaps (the honest list)
1. **Media is plaintext at rest.** `media_service.py` has no encryption path; an encrypted
   journal entry still leaves its photo readable on disk (and in backups / cloud copies).
2. **No backup integrity manifest.** `backup_service.py` has no checksums, so bit-rot or a
   truncated upload surfaces only as a gzip CRC failure at restore time — not before.
3. **No restore dry-run / verification step.** The UI restores blindly; nothing proves the
   archive matches the live DB before replacing it.
4. **No key-recovery story** for encrypted items: losing the app secrets means permanent
   ciphertext. (Needs confirmation of the current key source — `core/security.py`.)
5. Screen-capture and TTS scratch files: confirm temp-file lifetime and cleanup.

### Proposed change (four deliverables)
1. **Encrypted media for encrypted parents.** Encrypt attachment blobs with the same key
   hierarchy when the owning entry/note is encrypted; store a `media.encrypted` flag (inline
   migration) and decrypt on serve. Plaintext media stays supported for unencrypted parents;
   add a one-shot "encrypt existing media of encrypted items" maintenance job.
2. **Backup manifest.** Write `manifest.sha256` (path + size + sha256 per member, plus a digest
   of `lifelogr.db`) into every archive. On restore: verify first, abort on mismatch, report the
   offending members. Add a **Verify backup** button that checks a chosen archive without
   restoring.
3. **Restore dry-run.** A "check" mode that opens the archive read-only, validates the manifest,
   counts entries/media/notes and reports what would be replaced — before the destructive path.
4. **Recovery kit.** Export the encryption key material wrapped with a user passphrase (scrypt →
   AES-GCM), plus a printable 24-word recovery code; a "Restore keys" flow. Document it in
   `USER_MANUAL.md`.

### Acceptance criteria
- With encryption on, `strings`/`file` on the media directory shows no decodable image for
  encrypted items; the serve endpoint still renders them in-app.
- Corrupting one byte of a backup makes restore refuse with the member name; the live DB is
  untouched.
- Dry-run reports counts without writing; the "Verify" button returns green/red for a valid or
  damaged archive.
- A recovery kit round-trips: export with passphrase → wipe keys → restore → decrypt an item.
- Backup/restore and encryption integration tests extended; `make test` stays green.

### Risks
**Highest-risk item.** Media encryption changes the on-disk contract and backup format; needs a
format version bump and a backward-compatible read path. Key recovery is security-sensitive —
worth a short design review before implementation (see "Decisions").

---

## 5 — "Sniper fail in Notes" → Wayland screen capture

### What actually happens
The screenshot in `docs/assets/image.png` reads:

> **Screen capture failed:** Cannot find required wayland protocol. On Wayland, approve the
> portal request or run under X11.

- Capture is `xcap` in Rust: `desktop/src-tauri/src/main.rs:288-305`
  (`xcap::Monitor::all()`, then `capture_image()`).
- `xcap` 0.9's Wayland backend needs the `zwlr_screencopy_manager_v1` protocol. **GNOME does not
  implement it** (only wlroots-based compositors do), and this machine is
  `XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=ubuntu:GNOME`.
- The portal interface **is available**: `org.freedesktop.portal.Screenshot` version **2** on
  `org.freedesktop.portal.Desktop`, served by `gnome.portal`.
- `ashpd` is not a dependency (only transitive `zbus`); `grim` and `gnome-screenshot` are
  installed, but `grim` cannot work on GNOME.
- The frontend message (`NoteEditor.vue:636`) tells the user to approve a portal prompt that the
  backend never triggers — the advice is currently impossible to follow.

### Proposed change
1. Add `ashpd` (feature-gated behind `snip`; `ashpd` already speaks zbus) and implement a
   `wayland` capture path:
   - `Screenshot::request().interactive(false)` → returns a file URI for the full screen, which
     feeds the existing `SnipOverlay` crop flow unchanged.
   - If the portal returns denied/unavailable, retry `interactive(true)` — GNOME's own region UI
     runs, and the returned image is used **as-is** (skip our crop overlay).
2. Keep `xcap` for X11 (`XDG_SESSION_TYPE != wayland`).
3. Fall back to `gnome-screenshot -f <tmp>` when the portal is missing but the binary exists;
   error clearly only when all three are unavailable.
4. Rewrite the frontend error to name the actual failing path ("GNOME portal denied", "portal
   missing", "X11 capture failed") instead of the generic advice.
5. Verify the portal call does not require `libpipewire` (it shouldn't — builds with
   `--no-default-features` stay working).

### Acceptance criteria
- On GNOME Wayland, the snip button shows the portal prompt once, then the capture lands in the
  crop overlay; second use does not re-prompt (portal permission is remembered).
- On X11 the xcap path is unchanged.
- Denying the prompt yields a toast naming the denial, no stuck overlay, no console error.
- `cargo check` / `cargo clippy` clean with and without the `snip` feature; a smoke test script
  (`scripts/snip-smoke.sh`) documents the manual check.

### Risks
Medium: portal behaviour differs by GNOME version and by Flatpak vs deb; needs manual testing on
the target machine. Interactive fallback changes UX (selection happens in the shell).

---

## 6 — Notes draggable, droppable, nestable

### What's there (verified — more than expected)
- Nested folders: `NoteFolder.parent_id`, recursive tree rendering
  (`NotesView.vue:187-226`), inline "new sub-notebook" (`newFolderParent`), and a **cycle guard**
  in `note_service.update_folder` (`_would_create_cycle`, silent no-op).
- Moving a note between notebooks already exists via the editor dropdown
  (`NoteEditor.vue:737` → `store.updateNote({ folder_id })`), plus `clear_folder`/`clear_parent`.
- Page reordering inside a note is already drag-and-drop (`NoteEditor.vue:379-393`).

### Gap
Only the **drag interaction** is missing in the rail. The cycle guard also fails *silently*, so a
bad drop would look like a broken drag rather than a rejected move.

### Proposed change
1. HTML5 drag on tree rows (`draggable="true"`), reusing the pattern already proven in
   `layout/Sidebar.vue:55-186` (drag index, `dragover` target highlight, `drop`).
2. Drop targets:
   - on a folder row → file the note into it / nest the folder inside it;
   - between rows (3 px insertion line) → reorder within the parent (folders: `sort_order`;
     notes: pinned-then-updated order, so reordering notes is out of scope for v1);
   - on "Unfiled" / "All Notes" → `clear_folder`.
3. Folder reparenting uses the existing `PATCH /notes/folders/{id}`; pre-check the cycle client-side
   by walking `store.folders` and toast "A notebook cannot be moved into itself" — the backend's
   silent no-op then becomes unreachable in practice.
4. Optimistic update + rollback on error (store already exposes `updateNote`/`updateFolder`);
   `Esc` cancels a drag; auto-expand a collapsed folder when hovered for 600 ms.
5. Keyboard/context-menu parity: "Move to…" submenu on the row context menu and in the editor, so
   the feature is not drag-only (accessibility).

### Acceptance criteria
- Drag a note onto another notebook → it disappears from the source and appears in the target;
  survives reload.
- Drag a notebook onto another → nests one level deeper; drag onto itself or a descendant →
  rejected with a toast, no state change.
- Drop on "Unfiled" un-files; `Esc` aborts; no note is lost on a failed request (rollback tested).
- `NotesView.mount.test.ts` simulates dragstart/dragover/drop and asserts store calls.

### Risks
Low. The rail is virtualised — drop targets must resolve from `TreeItem` metadata, not DOM
indices; tests should pin that.

---

## 7 — Auto-title from first line

### What's there
- `EntryEditor.vue` binds a manual `title` input; `NoteEditor.vue` has a manual title field.
- Backend accepts `title` (max 255) on create/update for both; entries allow title-only records.
- No derivation logic anywhere (`autoTitle`, `firstLine`, `deriveTitle` → no matches).

### Proposed change
1. `frontend/src/utils/autoTitle.ts` — pure `deriveTitle(body, { max = 120 })`:
   first non-empty line, strip ATX headings/list markers/blockquote markers, strip inline
   markdown (`**`, `_`, `` ` ``, links → text, `![]()` → alt), collapse whitespace, trim trailing
   punctuation, hard-truncate on a word boundary + `…`. Returns `''` for bodies with no text
   (photo-only entries must not get a title).
2. Apply **on save** only when the title field is empty *and* the user has not typed/cleared it in
   this session (track `titleTouched`). Never overwrite a non-empty title.
3. Show a live ghost suggestion under the title input (`Title from first line: "…"`) with a
   one-click apply/disable, so it is not a surprise.
4. Setting `auto_title` (default **on**) in Settings → Editor; per-session override.
5. One-shot "Fill missing titles" maintenance action (preview count → apply), reversible via the
   normal title field. Do not run automatically on boot.

### Acceptance criteria
- Typing a body and saving leaves a title equal to `deriveTitle(body)`; editing the body again
  does not change an existing title.
- Photo-only/mood-only entries stay untitled.
- `autoTitle.test.ts` covers headings, lists, links, images, emoji, CJK, 1 k-char lines, empty
  bodies.
- Backend unaffected (no schema change).

### Risks
Low; the only real risk is surprise mutation of saved data, mitigated by "only when empty" and the
ghost preview.

---

## 8 — "Frequently the screen goes blank"

### What's there
- **No global error handling**: no `app.config.errorHandler`, no `window.onerror`, no
  `unhandledrejection` listener (`main.ts` installs only the router and Pinia). A render error in
  a component unmounts its subtree and can leave the shell empty with no message.
- Markdown previews render plain `<img src="/api/v1/media/{id}/file">` — `utils/markdown.ts` has
  no renderer override, so no `loading="lazy"`, no `decoding="async"`, no size cap, and **no use
  of the existing ≤640 px `/thumb` endpoint**.
- The thumbnail endpoint exists (`routers/media.py:194`) and is used by the media grid, timeline
  and map — but not by the editors, where long entries embed the most images.
- `AUDIT.md` already records WebKitWebProcess growing to ~5 GB and OOMing the machine under heavy
  media use; a killed web process is exactly a blank window.

### Working hypothesis
Blank screens are the renderer dying (OOM) or an unhandled render error, in that order. The plan
fixes both and adds telemetry so the next occurrence is diagnosable instead of anecdotal.

### Proposed change
1. **Contain errors (fast, independent of the cause).**
   - `main.ts`: `app.config.errorHandler`, `window.addEventListener('error')`,
     `unhandledrejection` → toast + `POST /api/v1/client-errors` (rate-limited, body capped,
     never includes entry text) → backend logs with context.
   - A top-level `<ErrorBoundary>` around the routed view with "Reload" and "Copy details".
2. **Cut renderer memory.**
   - Markdown image renderer: use `/media/{id}/thumb` when the body URL has no explicit
     `?w=&h=`, add `loading="lazy" decoding="async"`, and set an intrinsic
     `width`/`height` (from media metadata where available) to avoid layout thrash.
   - Keep `/file` for the media viewer, OCR and explicit-size images.
   - Cap concurrently decoded inline media per preview (e.g. 12) with a "Show N more" control.
   - Revoke object URLs on unmount/save; drop the preview DOM on route change.
3. **Detect a dead/blank renderer.** A 5 s heartbeat (`fetch /health` + `visibilityState`) that,
   after two missed beats or a `window` `pageshow` from bfcache, shows a reload overlay; log a
   `renderer_unresponsive` event so occurrences are counted.
4. **Instrument.** Log `performance.memory` (Chromium) / `performance.measureUserAgentSpecificMemory`
   where available every 30 s in dev, and always on user-reported "blank screen" (a
   "Report a blank screen" entry in the health banner).

### Acceptance criteria
- Injecting a render error in a test component shows the boundary with Reload, not a white page.
- Opening the largest media-heavy entry keeps WebKitWebProcess RSS below ~1.5 GB (measured via
  `ps` in a Playwright script on Linux) and the preview uses `/thumb` for unsized images.
- A simulated missed-heartbeat shows the reload overlay within 15 s.

### Risks
Medium: thumbnail substitution must not degrade OCR (OCR runs on `/file` server-side, unaffected)
or the media viewer (explicitly keeps `/file`). Heartbeat polling must not wake the CPU when the
window is hidden.

---

## 9 — App takes time to close

### What's there
- `main.rs:478-505`: `RunEvent::ExitRequested` runs **synchronously on the event loop**:
  `child.kill()` → poll `port_is_listening` every 100 ms for up to **5 s**
  (`SIDECAR_GRACE_MS`) → fallback `shutdown_sidecar()` which runs `pkill -f lifelogr-backend`
  (a full `/proc` scan) → polls another 3 s.
- `backend/app/main.py:135` → `SchedulerService.shutdown()` → `sched.shutdown()`; APScheduler's
  default is to wait for running jobs, so a backup/enrichment job can hold the process open.
- The window disappears before this finishes, so the user sees "nothing happens" for up to ~8 s.

### Proposed change
1. **Backend teardown is bounded.** `sched.shutdown(wait=False)`; wrap scheduler, enrichment,
   weather and Ollama close in one `asyncio.wait(..., timeout=1.5)`; log per-step durations so a
   future slow step is visible.
2. **Tauri close is non-blocking.** On `ExitRequested`: hide the window immediately, move teardown
   to a `std::thread`, wait at most **750 ms** for the port to close, then SIGKILL the exact child
   PID, then `std::process::exit(0)`. Never poll for 5 s on the UI thread.
3. **Kill precisely.** Replace `pkill -f lifelogr-backend` with the `SidecarChild` handle (already
   stored) and, for the fallback path, `kill(pid, SIGTERM)` on the PID that owned the port — the
   same precision `reclaim_port` already uses.
4. **Make it measurable.** `LIFELOGR_SHUTDOWN_TRACE=1` prints timestamps per step; add
   `scripts/close-timing.sh` that launches the app, requests close and reports
   close→process-exit.

### Acceptance criteria
- Window closes immediately (< 150 ms perceived) and the process is gone within 1 s (p50) /
  1.5 s (p95) with no scheduler job running; ≤ 2.5 s with a job in flight.
- No orphan `lifelogr-backend` and port 18765 free within 2 s (checked by script).
- An unrelated process named `lifelogr-backend` is never touched (PID-precise kill).

### Risks
Medium: exiting too early can truncate a DB write. Mitigation: the backend finishes its own
SIGTERM teardown, and the grace window still waits for the listening socket to close before the
hard kill; WAL makes the DB crash-safe regardless.

---

## Cross-cutting implementation notes

- **No new dependencies** except `ashpd` (item 5) and, if needed, nothing else — thumbnails,
  palette and error reporting reuse existing modules.
- **Migrations:** media encryption adds `media.encrypted` (inline `_COLUMN_MIGRATIONS`,
  `_SCHEMA_VERSION` bump). Everything else reuses existing columns.
- **Test gates per wave:** `make lint test` (ruff + mypy + pytest), `make fe-typecheck fe-test
  fe-lint`, and `cargo check` for items 5/9. Docs updated in `CHANGELOG.md` `[Unreleased]`,
  `ARCHITECTURE.md` where behaviour changes, `USER_MANUAL.md` for user-visible features.
- **Feature flags:** item 4 ships behind a setting (`encrypt_media`, default off until the
  migration job is proven on a copy).

## Decisions (resolved 2026-11-07)

1. **Item 1** — per-notebook/note colour labels; a Notes nav accent is not required.
2. **Item 2** — paste while in edit mode, in **both** editors. The mechanism already works
   (`embedMediaFile`/`embedFile` flip `showPreview`, wrappers are injected); WebKit simply draws
   no grip for a CSS `resize: both` element. The work is the **affordance** plus the memory fix,
   not new resizing logic.
3. **Item 4** — media encryption at rest **is** required; the recovery kit is part of the scope.
4. **Item 9** — do **not** hard-exit during a backup: show a bounded "Finishing backup…" wait
   (≤ 120 s, cancellable) and exit after the job completes. Idle closes stay fast.

## Out of scope

- WebKitWebProcess's own memory ceiling (environmental); item 8 reduces our contribution, it
  cannot cap the engine.
- Cloud sync as a product surface (removed from the router in the 2026-10-28 audit).
- Rewriting the editor to WYSIWYG. Resizing and media stay markdown-preview based.
