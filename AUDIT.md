# Production Readiness Audit — 2026-07-18

Branch: `cleanup/pipeline-2026-07-18` (off `feature/perf-and-debloat`). Source: 6 parallel
read-only subagent audits (correctness/error-handling, security, config/environment,
observability, testing/CI, operational-readiness), each verifying findings against the
actual code and self-correcting false positives. Headline blockers re-verified by the main
thread (`desktop/src-tauri/src/main.rs:271-272`, `backend/app/core/database.py:157-159`,
`backend/app/services/scheduler_service.py:946-972`, `backend/app/routers/entries.py:453-483`).

## Summary

**Verdict: the web-deb distribution is production-ready for its intended use (local-first
single-user desktop app); the Tauri desktop distribution has one serious security blocker
(B1) and should not be shipped until fixed.** All 2026-07-12 prior fixes **held** under
re-verification (no regressions). The 2026-07-18 perf+debloat code is **correct and clean**
— no new security/correctness bugs were introduced by it. The findings below are either
(a) one new Tauri-specific vulnerability, (b) pre-existing robustness gaps in backup/restore
crash-recovery, or (c) pre-existing test-coverage gaps on two inbound critical paths.

> The single most urgent item is **B1**: the Tauri launcher never generates a `SECRET_KEY`,
> so Tauri installs encrypt every stored OAuth/IMAP/SMTP/cloud credential with the
> publicly-known string `"change-me-before-production"`. Anyone with the DB file decrypts
> them all. (The web-deb launcher does generate one — `build-web-deb.sh:179-204` — so the
> installed `/opt/lifelogr` app is fine.)

## Blockers (must fix before prod)

- [ ] **B1** — `desktop/src-tauri/src/main.rs:262-272` — **Tauri sidecar runs with the default `SECRET_KEY`.** The Rust launcher sets `DATA_DIR` + `APP_ENV=production` but never generates/exports `SECRET_KEY`. `config.py:127`'s default `"change-me-before-production"` is used, and `database.py:157-159` deliberately skips `validate_production()` when `DATA_DIR` is set. `config.py` does not read `.secret_key` (only the deb script does). Result: AES-256-GCM credential encryption (`security.py:29` derives the key from `SECRET_KEY`) uses a public key on every Tauri install. **Fix:** mirror `build-web-deb.sh` — `secrets.token_hex(32)` once → persist to `data_dir/.secret_key` (umask 0600) → export as `SECRET_KEY` in the sidecar `.env()` call.
- [ ] **B2** — `backend/app/services/scheduler_service.py:946-972` — **Local backup is not atomic on `SIGKILL`/power loss → truncated archive survives retention.** The tarball is written directly to its final path; the cleanup at `:968-969` only runs on a Python exception, and the retention sweep keys on filename/size so a half-written file looks valid. On restore day the user gets a corrupt tarball with no warning. **Fix:** write to `*.tar.gz.part`, `os.replace(...)` after the `tarfile` context closes; sweep `*.part` on startup.

## High priority

- [ ] **H1** — `backend/app/services/cloud_sync_service.py:1137` (`CloudSyncService.push`) + `backend/app/services/email_service.py:469` (`sync_account`/`sync_folder`/`_store_message`) — **the two inbound/write critical paths for sync have zero tests.** `pull()` is well-tested; `push()` (the upload half of two-way sync — encrypts, uploads, flushes) is not. The IMAP fetch-and-persist loop (MIME parse, UID dedup, contact extraction) is not. A bug here silently loses data to the cloud or silently drops inbound mail. (The 07-18 new code — tags, contacts.delete_many, security.load_stored_credentials — IS adequately tested.)
- [ ] **H2** — `backend/app/routers/entries.py:453-483` — **dedup `GROUP_CONCAT(id)` order is unspecified.** No `ORDER BY` inside the aggregate; SQLite documents the order as undefined. Today it happens to be ascending (PK scan) so "keep `id_list[0]`, delete rest" keeps the oldest — but a plan change or future SQLite can flip it and delete the original. **Fix:** `GROUP_CONCAT(id ORDER BY id)` (SQLite ≥ 3.44) or a min-id-per-group subquery. (Related: dedup keys only on `(date, body)`, so same-day entries differing only in title/mood/tags are collapsed — confirm or add `title` to the key.)
- [ ] **H3** — `backend/app/routers/{box,dropbox,onedrive,google_drive}.py` — **OAuth redirect-host inconsistency.** Box uses `http://localhost:18765`; the other four use `http://127.0.0.1:18765`. Providers treat these as distinct registered URIs; a mismatch 400s the flow or lands on an origin the SPA isn't served from. Pick one host for all five.
- [ ] **H4** — `scripts/build-web-deb.sh:243-264` + `frontend/src/api/client.ts:4` — **web-deb port-fallback breaks OAuth silently.** All five redirect URIs are hardcoded `:18765`, but the web launcher falls back to `8000-8019`/OS-assigned if 18765 is taken. On such a machine the web app starts but every "Sign in with…" backup button is dead with no user-visible error. (Tauri is unaffected — it pins 18765 and reclaims it.)
- [ ] **H5** — `backend/app/services/backup_service.py:209-250` — **cloud uploads leave orphaned partial objects on crash** (no abort-on-error, no startup reconcile against `backup_snapshots`). Over months, provider quota silently fills with half-backups.
- [ ] **H6** — `desktop/src-tauri/src/main.rs:274` — **Tauri sidecar kill may skip lifespan shutdown.** `kill -9`/OOM/uvicorn's 5s shutdown cap can terminate an in-flight backup mid-transaction (compounds B2). Pragmatic mitigation: make backups atomic (B2) + a `SIGTERM` handler in `main.py` calling shutdown logic with a hard timeout.
- [ ] **H7** — `backend/app/core/database.py` / `scheduler_service.py` — **no periodic WAL checkpoint.** `_checkpoint_wal_robust` only runs from the backup path; with backups disabled or infrequent, the `-wal` file grows unbounded → slow reads + slow boot `init_db`. Add a low-frequency (e.g. 6h) checkpoint job; log WAL size in `/health`.
- [ ] **H8** — testing: `email_service.send/save_draft` (SMTP) untested; `restore.atomic_restore` rollback branches (`restore.py:207-227`) tested only in pieces, not end-to-end; `ocr_service` test silently skipped in CI (`test_ocr_service.py:12` — tesseract not installed, `ocr` extra not in `--group dev`); `_calc_streaks` happy-path only.

## Medium / Low

**Medium**
- [ ] **M1** — `backend/app/services/note_media_service.py:152-159` — **`from-path` sensitive-dir denylist incomplete.** Sandboxed to `$HOME`+temp and denies DATA_DIR/`.ssh`/`.gnupg`/`.config`, but `~/.aws/credentials`, `~/.kube/config`, `~/.netrc`, `~/.mozilla`/`~/.thunderbird`, `~/.local/share/keyrings`, `~/.password-store`, browser-cookie dirs are importable and then downloadable as note media. **Fix:** invert to a media-extension allowlist, or extend the denylist.
- [ ] **M2** — `backend/app/core/config.py:127` + `.env.example:6` — **weak default `SECRET_KEY` ships in source.** A bare `uv run uvicorn` (no launcher) silently encrypts with the public key; `.env.example` repeats the placeholder. Make `SECRET_KEY` required (no default) so bare runs fail fast.
- [ ] **M3** — `desktop/src-tauri/src/main.rs:13-19` + `docs/BUILD_GUIDE.md` + `docs/manual/DEPLOYMENT.md` — **stale config naming.** Tauri reads `DIARI_PORT` (old app name); docs reference `DIARI_DATA_DIR` but `config.py:200` honors `LIFELOGR_DATA_DIR`. Users following docs to relocate data silently get nothing. Rename/read-both + update docs.
- [ ] **M4** — `backend/.env.example` — **incomplete.** 6 Settings fields undocumented incl. security-relevant `BACKUP_ALLOWED_ROOTS` and `MAX_IMPORT_SIZE_BYTES`; `ANTHROPIC_API_KEY` is documented but never read (dead config — remove).
- [ ] **M5** — `backend/app/core/config.py:127` + `main.py:142,202` — **packaged web build runs `APP_ENV=development`** (so rate-limiting is off, intentionally) which also keeps `/docs` (Swagger) enabled on loopback. Introduce an `APP_ENV=desktop` mode that disables rate-limiting like dev but also disables `/docs`.
- [ ] **M6** — `backend/app/main.py:316-400` — **`/health` has no liveness/readiness split and makes a 2s Ollama call per probe.** Under any probe frequency it's a continuous load on SQLite+Ollama. Split `/health/live` (cheap) / `/health/ready` (full); cache Ollama reachability ~10s.
- [ ] **M7** — `backend/app/services/scheduler_service.py` — **APScheduler misfires/internal errors are not surfaced** (no `EVENT_JOB_MISSED`/`EVENT_JOB_ERROR` listener). "Why didn't my 9am backup run?" is unanswerable from the log. Add one listener logging misfires at WARNING.
- [ ] **M8** — `backend/app/services/backup_service.py:264-266` — **`run_backup` swallows the exception without `logger.error`** (persists to DB only). On-demand/HTTP-path failures leave zero log evidence.
- [ ] **M9** — `backend/app/services/cloud_sync_service.py` + `google_oauth.py:171` — **most cloud/Google API calls have no explicit read timeout** (only Nextcloud upload + token-refresh do). A stalled server hangs the sync job indefinitely, holding the sync lock. Set `httpx.Timeout(connect=30, read=300)` on shared clients.
- [ ] **M10** — `_run_email_sync`/`_run_google_sync` failures are logged but **not surfaced** (no `last_sync_error` written, no `/health` degradation). A week of failed syncs looks fine.
- [ ] **M11** — frontend: **zero unit tests** (no Vitest); `EntryEditor.vue` (1131 LOC, recently changed save flow) fully untested at unit level. e2e is narrow (settings/entries/recordings only) — Notes/Email/Planner/Backup/Encryption UIs undefended. (Accepted risk if Playwright-only is intentional.)
- [ ] **M12** — Phase-2 **R1**: `routers/sync.py:92` calls `encrypt(...)`+`flush()` while `backup_service.py` uses `reencrypt(...)` — cloud-provider construction triplicated and the two paths persist credentials differently. Unify deliberately (don't blindly merge).
- [ ] **M13** — `backend/app/services/planner_service.py:232-294` — naive/aware datetime mixing: a tz-aware `from`/`to` (e.g. `...Z`) 500s the agenda (`rrule.between` TypeError). Frontend strips offset today; coerce at the router boundary. Also: malformed `rrule` → broad `except` returns `[]` silently (no test).

**Low**
- [ ] **L1** — `backend/app/services/web_clip_service.py:74→:112` — small DNS-rebinding TOCTOU window between the per-hop `event_hooks` check and httpx's connect (already narrowed by per-hop re-validation; realistic only with attacker-controlled DNS + timing on a loopback app).
- [ ] **L2** — `backend/app/core/security.py:57-66` — `decrypt()` doesn't catch `InvalidTag`/`b64decode` itself; current callers wrap it, but a future direct caller leaks a stack trace. Wrap-or-document.
- [ ] **L3** — OAuth routers (`box.py:108`, `dropbox.py:111`, `onedrive.py:114`, `google_drive.py:115`) — raw upstream exception string rendered into the (escaped) HTML error page; may surface verbose provider errors. Truncate.
- [ ] **L4** — Phase-2 **R2**: `frontend/src/components/entry/EntryEditor.vue:343-347` — `onUnmounted` removes a **fresh** arrow listener that can never match the one registered at `:320` → the real listener leaks across unmount/remount. Hoist to a named const.
- [ ] **L5** — `backend/app/routers/tts.py:191-203` — TTS `.part` files leak when killed mid-synthesis (GC sweep globs `*.mp3`, not `*.mp3.part`).
- [ ] **L6** — `backend/app/services/contact_service.py:665-670` — `related_emails` LIKE pattern unescaped (`_` over-matches). Escape with an `escape` clause.
- [ ] **L7** — `backend/app/routers/encryption.py:129-132` — `decrypt-text` swallows errors with no log (correct for security, but no audit trail for repeated failures). One INFO line, no payload.
- [ ] **L8** — `backend/app/services/scheduler_service.py:404-410` — `shutdown()` doesn't pass `wait=True`/timeout explicitly; boot catch-up jobs (`backup_catchup`, `reminder_catchup`) missing `max_instances=1` (inconsistent with the pattern).
- [ ] **L9** — `desktop/src-tauri/src/main.rs:154` — `init_logging` `.expect()`s on log-file creation; a read-only/full data dir panics the launcher with no UI. Fall back to stderr.
- [ ] **L10** — `entry_service.py:231` / `note_service.py` search — FTS5 token-quoting doesn't double inner `"` (bound parameter → no SQL injection, only surprising self-query results).

## Verification of prior (2026-07-12) fixes — all held, no regressions

FTS5 excludes encrypted entries (`database.py:260-277`) · enrichment/themes/on-this-day skip encrypted entries (`entry_service.py:44,111`) · per-entry random salt + v1 legacy read-compat (`security.py`) · decrypt wrong-passphrase → 400 · `notes/from-path` sandboxed (`note_media_service.py:147-159`, *denylist incomplete — see M1*) · video/photo upload size+MIME+magic-bytes (`media_service.py:58-74`) · `OLLAMA_BASE_URL` scheme validated at the mutation path (`settings.py:216-224`) · OAuth error pages `html.escape`'d (all 4 routers + `google_sync.py:156`) · `LocalFileProvider` path-traversal containment (`cloud_sync_service.py:117-124`) · `get_db()` global-lock removal intact (`database.py:66-95`) · email-double-fire `asyncio.Lock` + `max_instances=1` intact (`scheduler_service.py:829-851`).

## Explicitly out of scope / accepted risk

- **Loopback trust boundary:** by design, any local process can reach the sidecar. This is inherent to the single-user desktop model; the trust boundary is correctly "anything already on the box can read the journal." Not treated as a finding.
- **`SECRET_KEY` auto-rotation intentionally not done** (would break already-encrypted credentials); the v1→v2 scheme anticipates a future rotation path. B1 is about the Tauri launcher not generating *any* key, not about rotation.
- **Dependency pinning** is solid for packaged builds (`uv.lock` + `uv export --frozen`). Note: `--no-hashes` in the export drops hash verification (consider keeping hashes).
- **EncryptionBadge.vue vs NoteEncryptionBadge.vue** ~85% duplication — intentionally not merged (med risk, marginal gain).
- **Frontend has no formatter** (backend has `ruff`) — adding prettier/eslint deferred pending owner decision (Phase 3 D1).

## Missed by pipeline, caught by blind review (Phase 5 reconciliation)

A context-blind reviewer caught a large set of real issues the six-dimension audit above
missed — concentrated in **concurrency/race conditions, FS/DB atomicity ordering, input
bounds/caps, and a few injection paths** the structured audit under-weighted. Full verbatim
review: `.pipeline/blind-review.md`. The main thread independently re-verified the
load-bearing new findings (✅ = re-confirmed against source here).

**Honest limit:** this subagent runs on the same model. The sanitized prompt removed
self-grading/framing bias (proven — it found ~32 things the structured audit missed), but
the reviewer **did find and read this `AUDIT.md`** at the repo root before reviewing, so its
*agreement* with B1/B2/H1/H8 is **not independent corroboration** (treat those as
single-source). Its **new findings** are the independent signal. For a fully independent
read, paste the source into a fresh session with no `AUDIT.md` present, ideally a different
reviewer.

### New HIGH (verified) — promote into the fix queue alongside B1/B2
- ✅ **N1** — `backend/app/routers/email.py:280-282` — inbound-mail attachment `filename` flows unsanitized into `FileResponse(filename=…)` → `Content-Disposition` **header injection / response-splitting**. One-line `_sanitize(att.filename)`.
- **N2** — `backend/app/routers/sync.py:84-146` — `on_refresh` flushes a refreshed token, but `db.commit()` only runs after `push()`/`pull()` returns; a raised push **rolls back the new refresh token** → OAuth silently and permanently broken.
- **N3** — `backend/app/services/google_sync_service.py:52-56` — mid-sync `on_refresh` commits the **shared session** while Calendar/Tasks syncs are in flight on it → breaks their per-service atomicity whenever the Google token refreshes mid-sync.
- ✅ **N4** — only `memorial.py` + `tts.py` use `asyncio.Lock`. `/sync/all` (`sync.py:151`), `/email/sync`, `/import`, `/storage-path` have **no concurrency guard** → overlap with scheduler-fired syncs (`database is locked`) and interleaved engine swaps on `/import`+`/storage-path`. One `asyncio.Lock` per path.

### New MEDIUM (verified)
- ✅ **N5** — `frontend/src/components/email/EmailView.vue:493-500` — `printEmail()` does `window.open` + `document.write(emailDocument(true))` into an **unsandboxed** window inheriting `tauri://localhost`; breaks the otherwise-consistent `sandbox=""` iframe discipline. Real XSS path (the only one — other `v-html` sites use DOMPurify).
- **N6** — `backend/app/core/restore.py:194-197` — pre-restore DB backup uses non-atomic `shutil.copy2`; a crash mid-copy truncates the **rollback target itself**. Use the existing `_atomic_write` (`:124`).
- ✅ **N7** — `backend/app/services/recording_service.py:43,113-122` — `threading.Lock` held across `await asyncio.to_thread(...)` **blocks the event loop**; should be `asyncio.Lock`.
- **N8** — `desktop/src-tauri/capabilities/default.json:10-11` — `fs:allow-read-file`/`allow-write-file` granted with **no scope**; combined with an XSS (N5) → arbitrary file R/W. Scope to `$HOME/*`. (Related: unused `shell:allow-execute`/`spawn` perms `:4-6`.)
- **N9** — `desktop/.../main.rs:152-160` + `build-web-deb.sh:268-269` — desktop/server logs **grow unbounded** (no rotation) → multi-GB over months.
- **N10** — `backend/app/services/tasks_sync_service.py:139-141` — pagination rebuilds `params` from scratch, dropping `updatedMin`/`showDeleted`/`showCompleted` on pages 2+ → re-processes already-applied updates, can revive soft-deleted rows.
- **N11** — `backend/app/services/email_service.py:96,1182-1214` — temp attachments leak on **abandoned compose** (sweep only runs inside `store_temp_attachment` / success paths).
- ✅ **N12** — `backend/app/services/media_service.py:202-205` (+ `note_media_service`, `video_service`, `entry_service`) — **`unlink()` before `db.commit()`**; a failed commit leaves the file gone but the row present. Unlink in `finally` after commit.

### New LOW (blind-verified; leads to confirm before acting)
N13 agenda no max-span (unbounded RRULE expansion) · N14/N21 no length cap on `ids`/`tag_ids` lists (`SQLITE_MAX_VARIABLE_NUMBER` → 500; malformed `tag_ids=1,abc` → `ValueError` → 500) · N15 TTS `text` no `max_length` (fan-out DoS) · N16 TTS `_locks` dict unbounded · N17 fire-and-forget `create_task` with no strong ref (GC mid-run) · N18 `video_notes` no `Range` support (breaks seek) · N19 `export_contacts(ids="")` silently exports all · N20 batch upload no rollback · N22 spam match on JSON column via `LIKE` (use `JSON_EACH`) · N23 `block_sender` unescaped `LIKE` · N24 Ollama tags GET no `follow_redirects=False` · N25 google `disconnect` commit-fail leaves stale job · N26 web-clip truncates after buffering full body · N27 ollama JSON-extract heuristic fragile · N28 `check_deps` "all_installed" copy-paste bug · N29 `reclaim_port` `pkill` too broad · N30 deb `prerm` no-op · N31 `/export/markdown` same-date entries overwrite · N32 `upload_temp_attachment` reads before size check.

### Agreement / disagreement
- **Agree (higher confidence, but single-source due to the AUDIT.md read):** B1, B2, H1, H8, the OAuth-router duplication (Phase 2 B3), the `encrypt` vs `reencrypt` drift (Phase 2 R1 / M12).
- **Blind review was STRICTER than the structured audit** on three whole classes the six dimensions under-covered: **concurrency/locking** (N4, N7), **FS/DB operation ordering / atomicity** (N6, N11, N12, N20, N31, N32), and **input bounds / DoS caps** (N13–N15, N21). These are genuine pipeline misses, logged here rather than folded quietly into the earlier sections.
- **No material disagreements** on what was reported; the blind review simply found more.
