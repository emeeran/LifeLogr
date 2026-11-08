# Production Readiness Audit — 2026-11-09

Third cleanup-pipeline pass (ship-readiness). Replaces the 2026-11-08 audit
(resolved items live in git history at `a35e8c5`). Six dimensions audited
independently by fresh agents: correctness/error-handling, security,
config/environment, observability, testing/CI, operational readiness. Every
2026-11-08 finding was re-checked against the current tree.

## Summary

**Ready with fixes.** This pass purged the stale planning docs, the divergent
build script, the Windows/macOS CI scaffolding and icon sets (app is
Linux-only), fixed the query-param 500s, the delete-before-commit media
ordering, the autosave race, and a batch of silent-failure paths (details
below). Backend and frontend test suites are green at every checkpoint
(1023 + 327). What stands between the current tree and a ship call: the
**Rust shell's two high-severity gaps** (a foreign port-squatter receives
journal content with only a log line; SIGTERM orphans the sidecar), the
**RAM-buffered exports** (this project has recorded OOM kills), and
**Docker's vacuous bind guard** on the web variant. All are enumerated below
with file:line refs; none are fixed in this pass.

## Fixed in this pass (verified by the audits where noted)

- Malformed query params (`month=13`, `tag_ids=abc`, bad dates) return 422,
  not 500 — shared `parse_tag_ids` helper, constrained/path-typed params
  (`routers/_params.py`, `routers/entries.py`, `routers/search.py`,
  `routers/notes.py`). Was the 2026-11-08 High item.
- Media/note-media/video deletes unlink files only after the DB commit
  (shared `unlink_media_file`), matching `EntryService.purge`'s rule.
- Corrupt-DB quarantine copies rotate (keep 3) — a failing disk can no
  longer write one full-DB-size file per boot attempt forever.
- AI provider `base_url` requires http(s) + host, validated in the Pydantic
  schema (`schemas/ai_provider.py:24-40`) — security audit verified.
- Autosave race: snapshot records the payload actually sent (keystrokes
  typed mid-flight are no longer marked clean), the debounced tick re-arms
  instead of dropping, and manual save awaits `whenIdle()` instead of racing
  an in-flight autosave. Regression-tested (`useAutoSave.test.ts`).
- `build_markdown_zip` moved from the entries router into `export_service`
  (router stays transport; pass-2 blind-review layering seam).
- `export_local_backup` stages in `DATA_DIR`, not tmpfs `/tmp`
  (`routers/backup.py:279-285`).
- GDrive `list_files` raises when both listings fail — a provider outage no
  longer masquerades as "No cloud backups found" during restore
  (`cloud_sync_service.py:755-777`).
- `useJobProgress` stops on 404 with a terminal failed state — resolves the
  pass-2 open question (unbounded 1 Hz poll) in favor of the blind review's
  reading; `run()`'s promise can no longer hang
  (`useJobProgress.ts:44-67`).
- Editor silent failures surfaced: clipboard cut keeps the selection when
  the write fails, delete distinguishes 404 from real errors, AI tag-suggest
  toasts (`EntryEditor.vue`).
- Reminder resync failures log at WARNING (was DEBUG — a silently unarmed
  reminder); scheduled backup drops its vestigial per-run `mkdtemp`.
- CI gates ESLint (tooling was installed but never run), runs all Playwright
  specs (was a hand-maintained list), Playwright `retries: 1`.
- Docs/config ghosts: `OCR_ENGINE` (documented, never read) removed;
  `DIARI_DATA_DIR` → `DATA_DIR` in DEPLOYMENT.md; `.env.example` documents
  `BIND_HOST`/`BIND_PORT`/`API_TOKEN`/`BACKUP_ALLOWED_ROOTS`/
  `MEDIA_IMPORT_ALLOWED_ROOTS`/`BACKUP_CLOUD_RETENTION`/enrichment
  concurrency; package-lock root version synced to 0.15.0; version-source
  count drift (four vs five) fixed.
- CHANGELOG cut into real 0.13.x/0.14.x/0.15.0 sections (ships in-app via
  Settings → What's New; previously everything since 0.12 sat in
  `[Unreleased]`).
- Pass-2 blocker verification: scheduled backups stage `.part` + `os.replace`
  and register with the shutdown guard — confirmed real and tested
  (`TestLocalBackupStaging`, `test_scheduler_service.py:528`).

## Blockers (must fix before shipping a release)

- [ ] `desktop/src-tauri/src/main.rs:370-377` — a foreign squatter on port
  18765 satisfies the port probe and `verify_sidecar_owner` only `warn!`s;
  every journal entry, note, and decrypted body is then POSTed to it with no
  UI signal. Should refuse to serve / abort with a visible error.
- [ ] `desktop/src-tauri/src/main.rs:710-719` — no SIGTERM/SIGINT handler
  (no signal crate in `Cargo.toml`; `RunEvent::ExitRequested` does not fire
  on signals). `systemctl stop`/logout/`kill` orphans the unauthenticated
  sidecar on 18765 holding the DB and WAL. Mitigated at next launch by
  `reclaim_port`, but the orphan window is real.
- [ ] `backend/app/services/export_service.py:236,436,853,951,1114` — the
  HTML, PDF, markdown (Obsidian + Diarium) and Day One builders buffer the
  entire archive in RAM (`BytesIO` + per-attachment `read_bytes()` + deflate,
  which burns CPU for ~0% on media) while the backup path streams. A
  media-heavy export in the same process serving the UI can OOM the machine
  (recorded incidents: 5 GB WebKit renderer OOMs). Stream to staged files in
  `DATA_DIR/tmp` like the backup path does.

## High priority

- [ ] `backend/app/main.py:588-676` — `/health` has no data-dir
  writability or `shutil.disk_usage` probe; writability is checked once at
  boot (`startup_checks.py:441`). A full or read-only volume keeps Docker
  "healthy" while every write 500s.
- [ ] `desktop/src-tauri/src/main.rs:147-163` — `port_is_lifelogr` matches
  any response containing "200"/"ok" before `fuser -k`; any JSON API on the
  port passes the heuristic and gets SIGKILLed. Match the exact `/health`
  contract shape.
- [ ] Docker/web variant: `Dockerfile` CMD hardcodes `--host 0.0.0.0` so
  the production bind guard (`config.py:451-455`) validates the unchanged
  127.0.0.1 default — a bare `docker run -p 8000:8000` exposes an
  unauthenticated API on all interfaces while the guard passes. The
  Dockerfile comment claiming boot-time bind validation is misleading.
  Related: `docker-compose.yml` still passes dev `.env` wholesale (dev
  `DATABASE_URL` lands outside the mounted volume — journal silently lost on
  container replacement).
- [ ] `DELETE /api/v1/media/{id}`, recordings/video-note/note-media deletes,
  and `DELETE /api/v1/backup/snapshots/{id}` are irreversible but sit
  outside the strict destructive-origin guard (`main.py:348-364`) — any
  loopback origin (hostile page on another local port) can enumerate IDs and
  mass-delete. Note the tradeoff: the destructive guard couples origin
  strictness with a 5/60s rate limit, which would break legitimate bulk
  media deletes; the fix needs those two concerns decoupled.
- [ ] `desktop/src-tauri/capabilities/default.json:27-36` — blanket
  `fs:allow-write-file` over `$DOWNLOAD/$DOCUMENT/$PICTURE/$DESKTOP/
  $HOME/Documents`; the only legitimate use is the user-picked save dialog
  (`utils/fileDialog.ts:29`). A compromised webview can overwrite arbitrary
  files in five trees with no dialog.

## Medium priority

- Media writes go straight to final paths with no temp+rename —
  `note_media_service.py:112,179,182,185`, `media_service.py:443,502,504`,
  `video_service.py:60,103` — ENOSPC mid-write leaves a permanent truncated
  orphan (thumbnails already do temp+rename correctly,
  `media_service.py:765-768`).
- No free-space checks before backup/restore/export staging
  (`scheduler_service.py:828-848`, `routers/backup.py:281,415` — restore
  peaks at ~2x data size across two filesystems), and no boot sweep for
  orphaned staged artifacts (`core/jobs.py:254-257`, `DATA_DIR/tmp`,
  crash-before-download leaks).
- `routers/media.py:69-90` batch upload commits per file with no per-file
  result: one bad file at position 12 of 20 → error naming nothing, and a
  retry duplicates the first 11.
- `main.rs:187-191` `pkill -f lifelogr-backend` fallback can kill unrelated
  processes matching the substring (psmisc ships in the .deb, so `fuser` is
  the normal path; the fallback is the dangerous branch).
- `capabilities/default.json:7` bare `shell:allow-open` — no URL validator;
  a compromised webview can invoke arbitrary schemes directly (frontend
  gating through `isExternalHref` is bypassable).
- `main.rs:39-44` + `tauri.conf.json:25` — `DIARI_PORT` env override is
  honored by the shell but the CSP pins `127.0.0.1:18765`; a non-default
  port silently breaks the webview's own API reach.
- `frontend/src/utils/markdown.ts:60-61` — `data-enc="${enc}"` unescaped
  while `escAttr` sits unused in the same file; an imported journal can
  inject attributes pre-sanitize (DOMPurify is the backstop; defense-in-depth
  breakage, not XSS).
- `BackupRestorePanel.vue:489-503` — disabling auto-backup swallows a failed
  schedule DELETE: the switch shows off while backups keep running, contrary
  to explicit user intent.
- `frontend/src/stores/tts.ts` (267 lines: object-URL lifecycle, audio
  caching) has zero tests; no frontend coverage measurement at all (backend
  has a 78% floor) — asymmetric ratchet.
- `backend/tests/unit/test_ocr_service.py:12` — the only real-OCR test skips
  in CI (no tesseract on runners); one `apt-get install` line closes it.
- `main.rs:385-401` — `init_logging` truncates the desktop log every launch
  (no post-mortem trail) and `.expect()`s on an unwritable data dir — the
  exact condition where diagnostics matter.
- `backend/app/main.py:609-611,614-670` — `/health` DB failures log ~30
  duplicate errors per failed boot (client polls at 2 Hz), and soft-check
  failures (FTS/scheduler) are never logged, only in a body nobody reads
  mid-boot.
- `Dockerfile:10,15` — floating `uv:latest`, resolves deps at build time
  while `uv.lock` (233 packages) is never COPYed; two builds of one tag can
  diverge.
- Reminder catch-up double-fire window (~seconds, notification-only;
  `_reminder_due_for_catchup` also ignores its `now_utc` parameter and uses
  naive local time — `scheduler_service.py:640-662,988-991`).
- Stats cache not invalidated on media mutations (stale media counts up to
  the 60s TTL; `entry_service.py:109-115` contract vs `routers/media.py`).

## Low priority

- Bulk dedupe bypasses `_drop_from_semantic_cache` — soft-deleted dupes can
  surface in semantic search until `ensure_fresh` self-heals
  (`routers/entries.py:995-1009`).
- `routers/search.py:22` — `q` has `min_length=1` but no max; megabyte
  queries reach FTS + embeddings (loopback-trusted, theoretical).
- `EntryEditor.vue:1066-1075` — `copyToClipboard` (post-fix) is fine, but
  non-secure-context clipboard denials now toast every attempt; consider
  once-per-session dedup if it ever bites.
- `semantic_cache.py:352` — embedding backfill scheduling failure logs at
  DEBUG; semantic search silently degrades to FTS-only.
- `scheduler_service.py:316-324,272-293` — auto_backup and backup_catchup
  are distinct jobs; `max_instances=1` is per-id, so a same-second overlap
  could interleave two tar writes to one staged path (narrow window).
- `frontend/src/components/search/SearchPalette.mount.test.ts:93` —
  real-timer 260 ms sleep where fake timers are the established pattern.
- `init_logging`'s `verify_sidecar_owner` `None => {}` branch silently
  ignores a missing port owner (`main.rs:375`).

## Explicitly out of scope / accepted risk

- **`trash2review/`** — holding pen for everything this pass parked
  (finished planning docs, `scripts/build.sh`, iOS/Android/Windows icon
  sets, genoffice manifests). Not dead weight until reviewed; see its
  README. Pass-2 `.pipeline/` artifacts are untracked now (retrievable at
  commit `a35e8c5`).
- **`SyncService.push/pull` incremental merge machinery** — no router caller
  since `/api/v1/sync` was parked; providers feed `backup_service` directly.
  Kept intentionally.
- **Rust shell has zero tests** — `main.rs` (~720 lines) is compile-gate
  only (`cargo check` in CI). Accepted boundary; the blockers above are
  exactly why that boundary is thin.
- **CSP `style-src 'unsafe-inline'`** (`tauri.conf.json:25`) — standard Vue
  compromise; everything else strict.
- **Local `backend/.env`** — holds real-format OAuth/AI secrets; untracked,
  never committed (`git log --all --full-history` empty — verified this
  pass). Rotate if used beyond dev.
- **`RATE_LIMIT` knob** (`config.py:346`) — one reader, one value; keep as
  env override or demote to constant, maintainer's call.
- **`services/` naming split** (24 `*_service.py` class modules vs bare
  function modules) — rename would be churn-heavy; documented, not fixed.
- **AI-settings field enumeration in three places** — deriving from
  `model_fields` was declined as a style trade-off.
- **Synchronous non-job `/restore`** (`routers/backup.py`) — UI uses the job
  variant; kept for compatibility.
- **Windows/macOS scaffolding removal** (this pass) — deliberate: the
  project is Linux-only per its charter; the deleted CI jobs and msi/dmg
  targets remain retrievable in git history.

## Missed by pipeline, caught by blind review

An independent sanitized cold review (`.pipeline/blind-review.md`, verbatim)
corroborated all three blockers above and the Docker bind-guard and
capabilities Highs (higher confidence now — though note the reviewer also
found and read `AUDIT.md` in the tree, so its agreement with existing items is
corroboration-with-knowledge; its new findings below retain full independence
value). What it caught that the six-dimension audit missed:

- **[Blocker] Entry-switch autosave wipe race** — the debounced autosave reads
  both the payload and the target id at fire time, and the editor's
  entry-switch watcher / unmount never cancelled it: switching entries with a
  save armed PATCHes the incoming entry with a cleared or foreign payload
  (silent content destruction). **FIXED same session** — `cancelSave()` in the
  switch watcher and `onUnmounted`, with a regression test that reproduces the
  wipe (`update(43, {body:''})`) without the fix (commit `f55bc5a`). Residual,
  flagged not fixed: keystrokes typed during a *create* round-trip are erased
  when the id-change reload clears buffers (`EntryEditor.vue:1020` region).
- **[Fixed] `check_deps` reported Ollama only** — `main.rs:73`
  `"all_installed": ollama` discarded the tesseract/GStreamer results, so the
  UI claimed all dependencies installed when OCR/audio were missing. **FIXED**
  (commit `f55bc5a`).
- **[Fixed] `make docs-check` could never fail** — BRE `\|` alternation inside
  `grep -hoE` matched nothing, and the docs had drifted to `0.11.0` stamps
  while the app is at 0.15.0. Regex is real ERE now (proven to fail on a
  stale version), docs re-stamped to 0.15.0. **FIXED** (commit `f55bc5a`).
- **[Regression from this pass, caught] `desktop/Makefile:47`** referenced the
  `UNAME_S` this pass's platform-trim had removed — `make setup` would always
  claim non-Linux. **FIXED** (commit `f55bc5a`).
- **[High] The production bind guard is dead code in every documented
  deployment** — `core/database.py:376-378` skips `validate_production`
  whenever `DATA_DIR` is set, and DEPLOYMENT.md's systemd unit, Dockerfile CMD,
  and bare-uvicorn instructions all either set DATA_DIR or refuse to boot. The
  audit's Docker-only framing was narrower than the reality.
- **[High] `shell:allow-spawn` with `"args": true`**
  (`capabilities/default.json:9-12`) — a compromised webview can spawn the
  backend binary with arbitrary arguments (`--host 0.0.0.0`, any DATA_DIR);
  the audit caught only the `fs:allow-write-file` half.
- **[High] Frontend stale-response race cluster** — no sequence guards in
  `stores/search.ts` (older hybrid search overwrites newer results),
  `stores/entries.ts` (fast month flip renders the wrong month),
  `stores/notes.ts` (note B's editor shows A's content), `stores/tts.ts`
  (audio plays A while the UI says B). Plus the non-404 half of the
  `useJobProgress` retry loop still retries forever (the 404 terminal state
  this pass added covers only eviction). One shared latest-wins/abort utility
  would close most of it — this is exactly the untested async-ordering surface.
- **[High] `BackupRestorePanel.vue:147-155`** — a failed backup download can
  save the backend's HTML error page as `backup.tar.gz` and toast success;
  `MaintenancePanel.vue:171-185` re-check/rebuild-index throw unhandled.
- **[Medium] Docker image installs the `ocr` extra but never
  `apk add tesseract-ocr`** — every OCR endpoint 500s in the web deployment;
  no `USER` directive means bind-mounted `./data` gets root-owned DB files.
- **[Medium] Soft-deleted notes have no restore UI** — `api/notes.ts`
  `restore()` has zero callers; `TrashView.vue` lists entries only.
- **[Medium] Reminder TZ-frame bug** — `_reminder_due_for_catchup` ignores its
  `now_utc` parameter and uses naive local `datetime.now()` while
  `schedule_catchup` compares UTC (`scheduler_service.py:988,663`); the audit
  logged the naive-now detail but not the frame mismatch.
- **[Medium] Empty single-instance handler** (`main.rs:559-561`) — second
  launch does nothing where the comment promises "focus existing window".
- **[Medium] Packaging nits** — `scripts/build-web-deb.sh:34-35` falls back to
  version `0.1.0` on a failed grep instead of failing; postrm purge leaves a
  dangling `/usr/local/bin/lifelogr` symlink.
- **[Style, not defects] Comment density is high-maintenance** — threat-model
  paragraphs on nearly every block will drift faster than the code; duplicate
  `_checkpoint_wal_sync`/rotation logic between `database.py` and
  `scheduler_service.py`. Left as-is (behavior-preserving pass).

**Open question from pass 2, now resolved:** the `useJobProgress` unbounded
1 Hz retry was bounded this pass (404 terminal state); the blind review still
flags the non-404 path as retrying forever (listed above with the race
cluster). The pass-2 disagreement is settled in the reviewer's favor, with the
404 half already fixed.

**Honest limit:** the blind reviewer runs on the same underlying model as the
audit agents — context-blindness removes self-grading and framing bias, not
shared model blind spots. It also found `AUDIT.md` at HEAD mid-review, so its
corroboration of known items is not fully independent. For a genuinely
independent signal, run the same cold-review prompt in a fresh session or hand
it to a different reviewer.

## Verification note

Findings carry file:line refs from six independent audit agents run against
this tree (branch `cleanup/pipeline-2026-11-09`, commits `ca66d8e`..`f55bc5a`).
Fixed-in-pass items were re-verified by the corresponding dimension agent or
by tests noted above. The Phase 5 sanitized cold review is preserved verbatim
in `.pipeline/blind-review.md` and reconciled in the section above.
