# LifeLogr — task list for `modify-idea.md`

Generated 2026-11-07 from `docs/plans/2026-11-07-modify-idea-plan.md`.
IDs are stable — reference them in commit messages (`COL-2`, `BLANK-4`, …).

**Gate for every task:** `make lint test && make fe-typecheck fe-test fe-lint`, plus
`cargo check` in `desktop/src-tauri` for CAP/CLOSE tasks. Update `CHANGELOG.md` under
`[Unreleased]` in the same commit as the behaviour change.

---

## Wave 0 — confirm scope (do first, ~1 session)

- [x] **DEC-1** Confirm item 1: per-notebook/note colour labels — or a Notes nav accent too?
      **Answer:** colour labels as planned.
- [x] **DEC-2** Reproduce item 2 on this build: paste an image in journal and note editors,
      drag the corner, reload. Record which of the three causes applies.
      **Answer:** paste (not drag), both editors, while in edit mode. Code inspection: both paste
      paths (`EntryEditor.embedMediaFile`, `NoteEditor.embedFile`) already flip
      `showPreview = true` for images, and `useResizableMedia` wraps them. Cause **(1)
      discoverability**: WebKit renders no visible grip for a CSS `resize: both` element, so
      there is nothing to grab. Fix the affordance (RESIZE-2), not the mechanism.
- [x] **DEC-3** Confirm item 4 scope: encrypt media at rest (format change) vs accept-and-document.
      If yes, confirm the recovery kit is mandatory.
      **Answer:** encrypt media at rest. Recovery kit proceeds as SEC-KEYS.
- [x] **DEC-4** Confirm item 9: hard exit after 750 ms is acceptable (no waiting for in-flight
      backups).
      **Answer:** **wait** for an in-flight backup. CLOSE-3/6 below updated: show a
      "Finishing backup…" dialog and wait (bounded), only then exit.
- [ ] **DEC-5** Create one issue per wave; link this file.

**Done when:** each DEC has a one-line answer recorded at the bottom of this file.

---

## Wave 1 — quick UX wins

### MIC — microphone next to the speaker (item 3)

- [x] **MIC-1** Move the trigger button out of `FloatingRecorder.vue`'s corner wrapper
      (`absolute bottom-20 right-4`) into the bottom toolbar in
      `EntryEditor.vue` next to the TTS `Volume2` button; match the `p-1` icon-button styling.
- [x] **MIC-2** Keep the recording pill (meter + timer + Stop) as a popover anchored
      `absolute bottom-20` above that button; keep the existing transitions and
      `startMeter`/`stopMeter` lifecycle untouched. The FAB was removed.
- [x] **MIC-3** Move `FloatingPlayback` into the same bottom dock. **Verified:** it already
      occupies the same bottom band (`bottom-20`, centred) as the recording pill; only the
      trigger needed moving.
- [x] **MIC-4** Show the mic in `focusMode` too (floating button; the controls bar stays hidden).
- [ ] **MIC-5** Mount test: mic and speaker are siblings in the toolbar; `aria-label` switches
      between `Record voice memo` and `Stop recording`; pill is above the button.
      *(not written — needs an EntryEditor mount harness)*
- [ ] **MIC-6** Manual check at 380 px, 720 px and fullscreen: no overlap with the editor body.

### COL — note & notebook colours (item 1)

- [x] **COL-1** `frontend/src/utils/noteColors.ts`: 8 named tokens, light/dark values,
      `contrastRatio()`; unit tests for contrast and unknown values falling back to `none`.
- [x] **COL-2** `NotesView.vue`: 3 px colour stripe on folder rows and a dot on note rows;
      inherit folder colour when the note has none; add `data-color` + aria-label naming the colour.
      (Implemented as a stripe/dot span; the accessible name carries the colour.)
- [x] **COL-3** Colour popover in the folder row → `store.updateFolder` (new store method).
- [x] **COL-4** Colour popover in `NoteEditor` header → `store.updateNote({ color })`; "None" entry.
- [x] **COL-5** `NoteColorPicker.mount.test.ts`: trigger naming, 8 swatches, checked state,
      emitted value, None. *(tree-row DOM assertion skipped — the rail is virtualized and
      happy-dom has no layout)*
- [x] **COL-6** `USER_MANUAL.md` Notes section: colour labels documented.

### TITLE — auto-title from first line (item 7)

- [x] **TITLE-1** `frontend/src/utils/autoTitle.ts`: `deriveTitle(body, {max=120})`.
- [x] **TITLE-2** `autoTitle.test.ts`: 12 tests (headings, lists, quotes, links, images,
      emoji, CJK, long lines, empty/photo-only bodies, surrogate pairs).
- [x] **TITLE-3** `EntryEditor.vue`: `titleTouched`, apply on save, `Auto:` chip; the old
      "Title this entry" prompt is skipped when the body yields a title.
- [x] **TITLE-4** `NoteEditor.vue`: same behaviour for notes and pages.
- [x] **TITLE-5** Settings → Appearance: `auto_title` toggle (default on).
- [x] **TITLE-6** Maintenance panel: **Fill missing titles** — dry run first
      (`POST /entries/backfill-titles?dry_run=true`, count + samples), second click applies.
      `services/title_service.py` mirrors `deriveTitle`; 11 Python tests use the same cases as
      Vitest. A backfill also refreshes `sync_hash` so Diarium pulls stay quiet.
- [ ] **TITLE-7** Test: save with empty title fills it; editing the body again does not
      change it; photo-only stays untitled; a typed title is never overwritten.
      *(pure logic covered in both languages; the editor save-wiring assertions are still not
      written)*

**Wave 1 done when:** `MIC-*`, `COL-*`, `TITLE-*` checked, frontend suite green, manual pass on
the desktop build at 380 px and fullscreen.

---

## Wave 2 — stability

### BLANK — blank screen (item 8)

- [x] **BLANK-1** `main.ts`: `app.config.errorHandler`, `window.addEventListener('error')`,
      `unhandledrejection` → toast + rate-limited `POST /api/v1/system/client-errors`
      (no entry text; max 4 KB; dedupe by message+stack hash).
- [x] **BLANK-2** `routers/system.py`: `POST /client-errors` (204, 20/min, in-window
      dedupe, URL query/fragment stripped) + `GET /shutdown-state`.
- [x] **BLANK-3** `<ErrorBoundary>` around the routed view in `AppShell.vue` with Reload and
      "Copy details"; mount test proves a throwing child renders the boundary, not a blank
      page, and that the report carries no entry text.
- [x] **BLANK-4** `utils/markdown.ts` image renderer: no explicit `?w=`/`?h=` →
      `/api/v1/media/{id}/thumb`; `loading="lazy"`, `decoding="async"`, escaped attrs.
      Note-media URLs (no thumb route) are left alone. Covered in `markdown.test.ts`.
- [x] **BLANK-5** Preview cap: at most 12 inline media per render with a "Show N more"
      control (`useResizableMedia({ maxInline: 12 })`), tested with 15 images.
- [x] **BLANK-6** Object-URL hygiene: audited the three call sites (`tts.ts` store revokes the
      previous URL; NoteEditor snip revokes in `endSnip`; `fileDialog` revokes after download).
- [ ] **BLANK-7** Heartbeat: 5 s `fetch /health` while visible; two missed beats → reload
      overlay. *(deferred — a crashed/killed renderer cannot be detected from inside it; a
      native watchdog is the honest fix and needs its own design)*
- [ ] **BLANK-8** Playwright `tests/e2e/blank-screen.spec.ts`. *(deferred — no e2e harness in
      the repo yet; needs a running stack + browser install)*
- [x] **BLANK-9** `ARCHITECTURE.md` + `CHANGELOG.md`: error reporting, thumbnails, close guard.

### CLOSE — fast shutdown (item 9)

- [x] **CLOSE-1** `scheduler_service.py`: `sched.shutdown(wait=False)`.
- [x] **CLOSE-2** `main.py` lifespan: all teardown steps share a 2 s deadline
      (`asyncio.wait_for` per step), each step timed and logged.
- [x] **CLOSE-3** `main.rs`: `ExitRequested` → `api.prevent_exit()` + worker thread;
      polls `/shutdown-state`, emits `shutdown-pending` (UI dialog with "Close anyway"),
      hides the window, bounded stop, `std::process::exit(0)`. No event-loop blocking.
- [x] **CLOSE-4** PID-precise kill: SIGTERM to the process that owns the port (PyInstaller's
      Python child) plus the spawned child handle; `pkill -f` removed from the exit path.
- [x] **CLOSE-5** `scripts/close-timing.sh` measures launch → port → SIGTERM → process/port
      gone, with the §9 targets printed. Step timings are logged unconditionally.
- [ ] **CLOSE-6** Verify timings on a real desktop run. *(needs the GUI; not measured here)*
- [x] **CLOSE-7** `ARCHITECTURE.md`: close sequence + 2 s / 2.5 s / 120 s budgets.

### CAP — Wayland screen capture (item 5)

- [x] **CAP-1** `Cargo.toml`: `ashpd 0.14` (`screenshot`) + `url`, gated behind
      `snip-wayland` (default; separate from `snip`/xcap).
- [x] **CAP-2** `main.rs`: `portal_screenshot()` calls
      `org.freedesktop.portal.Screenshot` v2 with `interactive=false`, resolves the
      returned `file://` URI to a path and reads the PNG.
- [x] **CAP-3** Fallback chain: non-interactive portal → interactive (GNOME region UI) →
      `gnome-screenshot` → xcap (X11 only) → error naming every failed path.
- [x] **CAP-4** Frontend `NoteEditor.vue`: generic Wayland advice replaced with the backend's
      actual failure; the crop overlay handles either a full-screen or a pre-cropped image.
- [x] **CAP-5** `cargo check` passes with the default features (portal) — verified here.
- [x] **CAP-6** `scripts/snip-smoke.sh` checks the session, portal version and fallbacks, then
      prints the manual checklist (prompt, remembered permission, deny path, X11).
- [x] **CAP-7** `USER_MANUAL.md` Wayland snip steps + `CHANGELOG.md` fix entry.

**Wave 2 done when:** blank-screen e2e passes, close timings meet CLOSE-6, capture works on this
GNOME/Wayland machine and on X11, and no new lint/type/test failures.

---

## Wave 3 — notes interaction

### DND — draggable, droppable, nestable notes (item 6)

- [x] **DND-1** Row-level drag state in `NotesView.vue` (dragstart carries the `TreeItem`
      model via `application/x-lifelogr-tree`, never a DOM index).
- [x] **DND-2** Drop on a folder row → `store.updateNote({ folder_id })` for notes,
      `store.updateFolder({ parent_id })` for folders; the target row highlights.
- [ ] **DND-3** Insertion line between rows; on "Unfiled" / "All Notes" → `clear_folder` /
      `clear_parent`. **Partial:** dropping on **Unfiled** un-files and dropping a notebook on
      the **Notebooks** header moves it to the top level; between-row *reordering* is not done
      (notes have no `sort_order`, and folder reordering would need N sequential PATCHes).
- [x] **DND-4** Client-side cycle check (`isDescendant`) → toast
      "A notebook cannot move into itself"; the backend's silent no-op is unreachable.
- [x] **DND-5** Optimistic move with rollback, `Esc` cancels, auto-expand a hovered folder.
      **Done:** moves apply on the server response (the tree never shows a wrong state);
      `Esc` cancels a native drag (browser default → `dragend` clears state); a collapsed
      notebook expands after 600 ms of hover.
- [x] **DND-6** Accessibility parity: **Move to…** popover on every notebook row
      (`FolderMovePicker`), listing valid parents + Top level and excluding self/descendants.
      Notes already have the folder dropdown in the editor header.
- [x] **DND-7** `useNotesTreeDrag.test.ts`: 15 cases — valid moves, no-ops, self-drop,
      descendant cycle, corrupt-list termination. `FolderMovePicker.mount.test.ts`: 5 cases.
      *(DOM drag assertions are skipped: the rail is virtualized and happy-dom has no layout)*
- [x] **DND-8** `USER_MANUAL.md` Notes → "Moving things".

### RESIZE — pasted image resizing (item 2)

- [ ] **RESIZE-1** ~~Close **DEC-2** with a written repro~~ — **done**: paste, both editors, edit
      mode; cause is affordance (see Decisions log). Skip the repro, proceed to RESIZE-2.
- [x] **RESIZE-2** Explicit affordance: corner grip + `W × H` chip on hover/focus, plus
      keyboard resize (arrows, `Shift` = larger step). Implemented in
      `useResizableMedia.ts` (grip drives the existing settle/persist path) + `main.css`.
- [x] **RESIZE-3** Video blocks: verified `applyMediaSize` already rewrites both markdown
      images and `<img>`/`<video ... src>` HTML tags, so a resized video persists the same
      `?w=&h=`. Audio is not resized (unaffected).
- [x] **RESIZE-4** Initial insert width = `min(intrinsic, 480 px)`, aspect preserved
      (`fitMediaSize`/`initialMediaSize`), applied in both editors; the grip grows it again.
- [x] **RESIZE-5** Unsized images render from `/thumb` via the markdown renderer
      (BLANK-4); an explicit `?w=&h=` keeps the full-size `/file` source.
- [x] **RESIZE-6** `useResizableMedia.test.ts`: grip presence, drag → `onResize`, min-size
      clamp, keyboard steps, no commit without a pointerdown on the grip.
- [ ] **RESIZE-7** Playwright: paste → drag → reload → size identical; downsize to 320 px decodes
      only the thumbnail. *(needs the e2e harness from BLANK-8)*

**Wave 3 done when:** DND + RESIZE checked, both editors pass the mount/Playwright tests, and a
manual session moves 10 notes and 3 notebooks without losing one.

---

## Wave 4 — data safety and security (item 4)

> Gate: **DEC-3** confirmed. Ship behind `encrypt_media` (default off) until proven on a copy.

### SEC-MEDIA — media encryption at rest

- [x] **SEC-MEDIA-1** Design note in `docs/design/media-encryption.md` (key hierarchy,
      chunked-AEAD blob format, Range mapping, policy, migration, failure modes, rollout).
- [x] **SEC-MEDIA-2** Implement chunked reader/writer + `ENCRYPT_MEDIA` flag; no schema change
      (magic sniffing). Codec in `services/media_crypto.py` (encrypt/decrypt/range, on-disk
      `probe_file`/`read_range_file` that seek only the chunks a range needs); flag in
      `core/config.py` (default off — it gates uploads only, serving always decrypts).
      20 codec unit tests.
- [x] **SEC-MEDIA-3** Encrypt on upload when the parent item is encrypted; decrypt on serve
      (`/file`, `/thumb`, OCR) with path-bound AAD. Both `MediaService` and
      `NoteMediaService`; `media_file_response` shared by both routers maps auth failure →
      409 (file untouched); `file_size` records ciphertext. 7 integration tests in
      `test_media_encryption.py` (flag off/on, plaintext items, Range 206/416, tamper 409,
      encrypted note media).
- [x] **SEC-MEDIA-4** Encrypted thumbnail cache (`.webp.llm1` sibling, rendered from
      decrypted bytes, thumb path as AAD) — served decrypted via `/thumb`; a stale
      plaintext WebP sibling is deleted when the encrypted cache is written, and the
      migration purges pre-existing plaintext thumbs (SEC-MEDIA-5).
- [x] **SEC-MEDIA-5** Maintenance "Encrypt attachments of encrypted items"
      (`services/media_migration.py`, `POST /settings/encrypt-media`, dry run first,
      resumable, atomic per file with fsync, failures keep the original and are named).
      Purges stale plaintext thumbs. UI row in Maintenance (two-step, shown only when
      `ENCRYPT_MEDIA` is on, via the new `security` block in `GET /settings`). 5
      integration tests in `test_media_migration.py`.
- [x] **SEC-MEDIA-6** Tests from the design note §12 (codec round-trip/tamper/AAD/range;
      wiring: flag on/off, Range 206/416, tamper 409, encrypted thumb cache, note media;
      migration dry-run/idempotency/purge; recovery kit round-trip incl. probes). The
      manual `strings`-on-media acceptance check stays with the real desktop run.
      **Code-review pass (pre-commit) fixed:** missing-file guard before the migration
      probe; **VideoNote clips of encrypted entries** now encrypt on upload, decrypt on
      serve and migrate (the third attachment store the first pass missed); delete
      removes the encrypted thumb sibling; recovery-kit media probe scans all rows
      (a sampled probe could skip and bless a wrong key); magic-prefix false positives
      (`looks_encrypted`) treated as plaintext; `bytes=-0` → 416; dead `decrypt_range`
      removed; thumb cache flavour derived from the blob (one query off the grid path).
- [x] **SEC-MEDIA-7** Exports no longer leak encrypted attachments: share exports
      (HTML zip, Obsidian markdown, Diarium-compatible markdown, `.diary`, Day One)
      omit attachments of encrypted entries — markdown records the omission in
      frontmatter. The **native archive** keeps them *as ciphertext* (restore needs
      the rows/files; design §9). 4 integration tests in
      `test_export_encrypted_media.py`.

### SEC-BACKUP — manifest, verify, dry-run

- [x] **SEC-BACKUP-1** Every archive carries `manifest.json` (format 2, app version,
      per-member size + sha256), hashed while writing — no second pass.
- [x] **SEC-BACKUP-2** Both restore paths verify before extraction/swap; failure names the
      member; legacy archives warn and proceed. Import returns 400 on failure.
- [x] **SEC-BACKUP-3** `POST /backup/verify` + **Verify** button (report only, nothing
      extracted or replaced).
- [x] **SEC-BACKUP-4** Dry-run inspect: `verify` returns created_at / app_version / file and
      byte counts, which the UI shows before a restore.
- [x] **SEC-BACKUP-5** Tests: valid archive, tampered member (named), missing member, legacy,
      unreadable archive; endpoint + import-rejection (6 + 3 tests).

### SEC-KEYS — recovery kit

- [x] **SEC-KEYS-1** Key source audited and documented in the design note §2 (SECRET_KEY →
      HKDF; domain-separated media info).
- [x] **SEC-KEYS-2** Export: `services/recovery_kit.py` — scrypt(n=2^15, r=8, p=1) → KEK →
      AES-GCM wrap of `SECRET_KEY` (AAD `lifelogr-recovery-kit-v1`), 24-base32 recovery
      code (grouped XXXX-) whose normalised form **is** the KDF input;
      `POST /settings/recovery-kit/export` returns the kit + code (never the raw key)
      and records the export timestamp in runtime settings.
- [x] **SEC-KEYS-3** Import/restore with probe decrypts: unwraps (passphrase literal
      first, normalised code form second), probe-decrypts one stored credential
      (`BackupConfig.credentials_encrypted`) and one encrypted media chunk, refuses a
      key that cannot read the data, requires `confirm_replace` before replacing a
      different non-default key, installs live (`security.rekey` + media-key cache
      reset + `.secret_key` 0600) and refuses unmanaged (env-sourced) runs.
      `POST /settings/recovery-kit/import`.
- [x] **SEC-KEYS-4** UI: new **Security** pill in Settings → Data (`SecurityPanel.vue`) —
      export (optional passphrase, downloads the kit, shows the code once), restore
      (file picker + passphrase + inline confirm-replace), and the one-time warning
      shown while media encryption is on and no kit has been exported.
- [x] **SEC-KEYS-5** Round-trip tests (export → key wipe → restore → credential readable
      again), plus: wrong passphrase, damaged kit, foreign-kit refusal via the media
      probe, confirm-replace flow, unmanaged-run refusal. 7 integration tests in
      `test_recovery_kit.py`.
- [x] **SEC-KEYS-6** `docs/SECURITY.md` (what is / is not encrypted, key hierarchy,
      failure mode, recovery kit, threat model); `CHANGELOG.md` entries; AUDIT.md
      security-wave section.

### SEC-AUDIT — scratch files & docs

- [x] **SEC-AUDIT-1** Audited temp/scratch paths — all clean, no code needed: TTS
      `.part` unlink on failure + LRU cache eviction; media/backup/entries import
      spools unlink in `finally`/`except`; jobs delete result files on discard;
      restore uses `TemporaryDirectory`; frontend object URLs audited in BLANK-6.
- [x] **SEC-AUDIT-2** `AUDIT.md` — new "Security wave — 2026-11-07" section: risks closed
      (plaintext attachments, key loss) and what remains accepted.
- [x] **SEC-AUDIT-3** `CHANGELOG.md` — recovery kit, migration and export-omission
      entries under `[Unreleased]`. Version bump left to the release cut
      (`make bump`), which drives the deb/AppImage names.

**Wave 4 done when:** SEC-MEDIA/BACKUP/KEYS/AUDIT checked, the restore/verify tests pass on a real
archive, and the manual `strings`-on-media check shows no decodable image for encrypted items.

---

## Tracking

| ID | Owner | Status | Commit |
|---|---|---|---|
| DEC-1…5 | | | |
| MIC-1…6 | | | |
| COL-1…6 | | | |
| TITLE-1…7 | | | |
| BLANK-1…9 | | | |
| CLOSE-1…7 | | | |
| CAP-1…7 | | | |
| DND-1…8 | | | |
| RESIZE-1…7 | | | |
| SEC-* | | | |

### Decisions log

- **DEC-1** — per-notebook/note colour labels (Wave 1 `COL`).
- **DEC-2** — paste in edit mode, both editors; resizing mechanism exists, the handle is
  invisible in WebKit. Fix the affordance, keep `?w=&h=` persistence.
- **DEC-3** — media encryption at rest is required (Wave 4 `SEC-MEDIA`); recovery kit included.
- **DEC-4** — do not hard-exit during a backup: show a bounded "Finishing backup…" wait, then
  exit (Wave 2 `CLOSE-3/6`).
