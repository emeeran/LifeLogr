# Phase 5 — Blind Review (verbatim, unedited)

Source: a single fresh subagent dispatched with a **sanitized prompt** — told only that it
was doing on-call due diligence on a codebase it had never seen, with no mention of this
cleanup pipeline, its phases, "debloat," `trash2review`, `AUDIT.md`, or that any refactor
had occurred. Scoped to the source directories. Output below is verbatim.

> ## Honest limit (read first)
> **Sanitization breach:** despite being scoped to source dirs and given no pointer to it,
> the reviewer explored the repo root, found `AUDIT.md`, and read it before reviewing
> ("I read it first, then independently re-verified"). That **taints its *corroboration***
> of B1/B2/H1/H8 etc. — it had the answer key for those, so its agreement is not independent
> confirmation. What is **NOT tainted** is the set of **new findings (N1–N32)**: those were
> not in `AUDIT.md`, and the reviewer verified each against source on its own. The main
> thread independently re-verified N1, N4, N5, N7, N12 against the code — all confirmed real.
>
> This subagent runs on the same underlying model as the pipeline. A sanitized, context-blind
> pass removes *self-grading bias* and *framing bias* (real, and the new-findings set proves
> it caught things the structured audit missed) — but it does not remove model blind spots,
> and in this case it did not fully remove *answer-key contamination* because `AUDIT.md` lives
> at the repo root. For a genuinely independent signal, the strongest move is pasting the
> source into a **brand-new session with no `AUDIT.md` present, ideally a different reviewer**.
> Treat the new-findings list below as high-value leads to verify, not as gospel.

---

# Technical Due Diligence — LifeLogr (`/home/em/code/wip/diary`)

**Scope:** FastAPI + async-SQLAlchemy/SQLite backend (~11k LOC services), Vue 3 + TS frontend, Tauri (Rust) shell. Processes untrusted email, web clips, OAuth, and local AI. Single-user loopback app — loopback trust boundary is treated as accepted risk.

A prior `AUDIT.md` exists at the repo root and is genuinely thorough (B1/B2 blockers, H1–H8, M1–M13, L1–L10). I read it first, then independently re-verified the headline items and ran four parallel reviews to find what it missed. Below is my independent verdict. **All NEW findings were verified against source by me, not just relayed.**

---

## Overall verdict

**Would I be comfortable being paged about this at 3am? For the web-deb distribution: yes, with caveats. For the Tauri desktop distribution: no, not until B1 is fixed.**

The codebase is meaningfully above average for a single-maintainer local-first app:
- SQLite pragmas are correct (WAL, `synchronous=NORMAL`, `busy_timeout=5s`, `foreign_keys=ON`).
- FTS5 triggers handle encrypt/decrypt transitions idempotently and correctly exclude ciphertext from the index.
- Crypto is done right where it matters: AES-256-GCM, HKDF-SHA256 key derivation, per-entry random salts, v1→v2 migration path, single-use OAuth state with TTL.
- Web-clip SSRF hardening is genuinely careful — per-hop re-validation including DNS-rebinding, and it's actually tested (6 tests in `test_notes.py`).
- Migration idioms are idempotent (`PRAGMA table_info` guards + `IF NOT EXISTS`).
- CI gates ruff + strict-mypy + pytest + frontend build + e2e on every PR and release tag — stronger than typical.

What would actually page me:
1. **B1 (Tauri SECRET_KEY)** — every Tauri install encrypts OAuth/IMAP/SMTP/cloud creds with the public string `"change-me-before-production"`. Anyone with the DB file decrypts them all. This is the only true blocker.
2. **Backup non-atomicity (B2)** + the related restore/orphan/partial-file family (H5, plus new finding N4 below) — on a crash mid-backup the user can end up with a corrupt tarball that looks valid, and on restore day there is no warning.
3. **Untested inbound critical paths** (H1: IMAP fetch+store loop, cloud `push()`, SMTP send). These are the paths most likely to silently drop mail or lose data to the cloud, and they have zero tests.

The rest is real but manageable: a handful of input-bounds gaps, some non-atomic FS/DB orderings, an XSS hole in `printEmail`, unbounded log growth, and templated-duplicated OAuth code across the 4 cloud routers.

---

## Blockers (must fix before on-call handoff)

### B1 — Tauri sidecar runs with the default public `SECRET_KEY`
`desktop/src-tauri/src/main.rs:262-272` (verified)
The launcher exports `DATA_DIR` and `APP_ENV=production` but never `SECRET_KEY`. `config.py:127`'s default `"change-me-before-production"` is used, and `database.py:157-159` deliberately skips `validate_production()` when `DATA_DIR` is set. Result: `security.py:29` derives the AES key from a publicly-known string on every Tauri install. The web-deb launcher (`scripts/build-web-deb.sh:179-204`) does generate one — so `/opt/lifelogr` is fine; only the Tauri build is exposed. **Fix:** mirror the deb script — `secrets.token_hex(32)` → persist to `data_dir/.secret_key` (umask 0600) → export in the `.env()` call.

---

## NEW findings (not in `AUDIT.md`) — verified

### High

**N1 — HTTP response-splitting via inbound email attachment filename.**
`backend/app/routers/email.py:280-282`. `att.filename` is the unsanitized MIME part filename from inbound mail (stored raw at `email_service.py:671`; only the on-disk path is `_sanitize()`'d at `:666`). It flows directly into `FileResponse(filename=...)` → `Content-Disposition` header. A `Content-Disposition: filename="x\r\nSet-Cookie: ..."` in inbound mail gives the attacker header injection on the loopback API the Tauri shell trusts. One-line fix: `FileResponse(path, filename=_sanitize(att.filename), ...)`.

**N2 — OAuth refresh-token rollback: failed `push()`/`pull()` invalidates the refreshed token.**
`backend/app/routers/sync.py:84-146`. The `on_refresh` closures (`:89-95, :107-113, :117-123`) mutate `config.credentials_encrypted` and `db.flush()` when the provider refreshes; `db.commit()` only runs at `:135, :146` *after* `push()`/`pull()` returns. If push raises after a refresh, the whole transaction rolls back including the new refresh token. Next attempt uses the now-invalid old token → OAuth flow permanently broken, silent. **Fix:** commit refreshed creds before the push, or catch+commit in a `finally`.

**N3 — `google_sync_service.py:52-56` mid-sync `on_refresh` commits the shared session.**
`on_refresh` calls `await self.db.commit()` while `CalendarSyncService(self.db,…).sync()` (`:62`) and `TasksSyncService(self.db,…).sync()` (`:68`) are mid-flight on the same session. The commit auto-flushes whatever the in-progress sync has staged. If the sync fails a few rows later, partial writes are already committed — the per-service atomicity the calendar/tasks syncs rely on is silently broken whenever the Google access token refreshes mid-sync. Worse than N2 because CalendarSyncService actively depends on per-service atomicity.

**N4 — No concurrency guard on `/sync/all`, `/email/sync`, `/import`, `/storage-path`.**
`backend/app/routers/sync.py:150-170`, `backend/app/routers/email.py:140-145`, `backend/app/routers/backup.py:188-265`, `backend/app/routers/settings.py:308-326`. Only the TTS and memorial routers use `asyncio.Lock` (verified by grep). The two sync HTTP entry points can overlap with APScheduler-fired syncs against the same SQLite DB → `database is locked` mid-sync, partial folder/message upserts, duplicate writes. The two engine-mutating endpoints (`/import`, `/storage-path`) call `reinit_engine()`/`init_db()` with no lock — concurrent calls interleave the engine swap and WAL/SHM state → corrupted DB or engine pointing at a stale path. **Fix:** one module-level `asyncio.Lock` around each of these four paths.

### Medium

**N5 — `printEmail()` writes raw email HTML into an unsandboxed window (real XSS path).**
`frontend/src/components/email/EmailView.vue:493-500`. `window.open('', '_blank')` + `w.document.write(emailDocument(true))`. The new window inherits the opener's origin (`tauri://localhost`) and is NOT sandboxed; any `<script>` in the email body executes with that origin. This breaks the otherwise-consistent `sandbox=""` iframe discipline used at `EmailView.vue:992` and `:1211`. The misleadingly-named `sanitizedHtml` computed (`:449-459`) only resolves `cid:` images, it does not sanitize. **Fix:** DOMPurify the body, or open the iframe's `srcdoc` in the print window instead of `document.write`.

**N6 — Pre-restore DB backup is non-atomic; rollback target can truncate on crash.**
`backend/app/core/restore.py:194-197`. `shutil.copy2` of a WAL-mode DB captures only the main `.db` (the `_checkpoint_live` at `:190-192` is best-effort). Worse, the copy itself isn't crash-safe — a crash mid-copy leaves a truncated `.pre-restore.bak`. Since this file IS the rollback target if the restore fails, truncating it during its creation means the rollback itself fails. `_atomic_write` exists at `:124` and does tmp+`os.replace` — use it for the backup too.

**N7 — `threading.Lock` held across an `await` blocks the event loop.**
`backend/app/services/recording_service.py:43,113-122`. `_active_lock = threading.Lock()` is acquired with `with _active_lock:` while `await asyncio.to_thread(...)` runs inside. A threading lock is NOT released when the coroutine suspends, so a second `start_recording`/`stop_recording` hitting the same lock blocks the **entire event loop** until mic open/close returns (worst case: seconds of frozen UI). **Fix:** `asyncio.Lock()`.

**N8 — `fs:allow-write-file` / `fs:allow-read-file` granted with no scope.**
`desktop/src-tauri/capabilities/default.json:10-11`. In Tauri 2 this means any IPC call from the webview can read/write any file the running user can. The only call sites go through the native dialog, so it's not directly exploitable through the UI — but if any XSS lands in the webview (N5 is one such path; AI/web-clip output is another), the overbroad fs scope turns it into arbitrary file read/write. **Fix:** scope to `{"path": "$HOME/*"}` (or tighter) and add a downloads scope. (Related: the three bare global `shell:allow-execute`/`spawn`/`stdin-write` perms at `:4-6` are unused attack surface — the frontend never calls `shell.spawn()`.)

**N9 — Desktop and server log files grow unbounded (no rotation).**
`desktop/src-tauri/src/main.rs:152-160` (`lifelogr-desktop.log`) and `scripts/build-web-deb.sh:268-269` (`server.log`, append mode). Combined with `info!("[backend] {}", …)` on every sidecar stdout line at `main.rs:288`, this reaches multi-GB on an active install over months. Operational: disk fills silently.

**N10 — `tasks_sync_service.py:139-141` pagination drops `updatedMin`/`showDeleted`/`showCompleted`.**
First page sets them (`:125-127`); subsequent pages do `params = {"pageToken": …}` from scratch, omitting all three. Google Tasks incremental sync requires `updatedMin` on every page; without it later pages return the full task set each cycle → re-applies already-processed updates, potentially revives soft-deleted rows, unbounded re-processing on paginating accounts. **Fix:** mutate `params` in place rather than rebuilding.

**N11 — `_TEMP_ATTACHMENTS` dict + on-disk files leak on abandoned compose.**
`backend/app/services/email_service.py:96, 1182-1214`. `_sweep_temp_attachments` only runs inside `store_temp_attachment`; `_cleanup_temp_attachments` only on the success paths of `send`/`save_draft` (`:1082, :1091`). An abandoned compose with multiple uploads leaks all of them — no scheduler job or startup sweep for `MEDIA_DIR/email/_temp/`. Slow unbounded disk growth on a long-running desktop process.

**N12 — Non-atomic delete: file unlinked before DB commit.**
`backend/app/services/media_service.py:202-205`, and the same pattern in `note_media_service.py:~192`, `video_service.py:~82`, `entry_service.py:124-133`. `full_path.unlink()` runs before `await self.db.commit()`. If the commit fails (SQLite "database is locked", disk full on `-wal`), the file is gone but the row remains — `get_file_path` then raises `NotFoundError` permanently for a row the user still sees. **Fix:** unlink in a `finally` after a successful commit.

### Low

- **N13** — `planner.py:126-144` `list_events`/`get_agenda` take `from_`/`to` with **no max span**. `from=1970&to=9999` forces RRULE expansion of every recurring event — unbounded CPU + memory on the loopback server. Cap `to - from_` to e.g. 365 days.
- **N14** — `email.py:185-195` + `contacts.py:99-103` `bulk_delete`/`bulk_delete_messages(ids: list[int])` have no length cap. SQLite's `SQLITE_MAX_VARIABLE_NUMBER` (999 or 32766) throws `OperationalError: too many SQL variables` → unhandled 500.
- **N15** — `tts.py:330-348, 369-407` `SpeakRequest.text: str` has no `max_length`. Multi-MB body flows through regex-heavy `_clean_markdown` + `_split_for_tts` → one Edge-TTS request per chunk = CPU + memory + API fan-out DoS.
- **N16** — `tts.py:60-61` module-global `_locks: dict[str, asyncio.Lock]` keyed by cache hash grows unbounded; LRU file eviction deletes `.mp3`s but never removes the corresponding lock entry. Slow memory leak.
- **N17** — `tts.py:407` and `ai.py:240-267` `asyncio.create_task(...)` fire-and-forget with no strong reference held. Per Python docs the task can be GC'd mid-execution; prewarm/pull silently never finishes. Fix: module `set` + `add_done_callback(discard)`.
- **N18** — `video_notes.py:48-58` reads whole video into RAM and serves no `Range` support (breaks `<video>` seeking). `media.py:130-146` and `tts.py` comments explicitly call this pattern wrong; this router didn't get the fix.
- **N19** — `contacts.py:75-81` `export_contacts(ids="a,b,c")`: parsed `id_list=[]` is falsy → silently exports *all* contacts when caller intended a subset. Treat empty parsed list as 400.
- **N20** — `media.py:44-59` batch upload has no rollback: if upload N fails, files 1..N-1 are persisted on disk and DB; earlier attachments orphaned.
- **N21** — `search.py:32` + `notes.py:83` + `entries.py:79` three copies of `parsed_tag_ids = [int(t) for t in tag_ids.split(",")]` with no try/except. Malformed `tag_ids=1,abc` → uncaught `ValueError` → 500; unbounded list exceeds SQLite bind limit.
- **N22** — `spam_service.py:238` matches `Contact.emails_extra` (a JSON list column) with `LIKE '%addr%'` — false positives (`a@b.com` matches `xa@b.comx`) and false negatives depending on JSON spacing. Use `JSON_EACH`.
- **N23** — `email_service.py:953-967` `block_sender` domain match `LIKE f"%@{domain}"` with unescaped pattern; `_` over-matches. Use `ESCAPE` clause.
- **N24** — `settings.py:257-276` `httpx.AsyncClient()` GET to `{OLLAMA_BASE_URL}/api/tags` without `follow_redirects=False`; existing SSRF scheme-check (`:216-224`) only validates the stored URL, not post-redirect target. Low impact (GET only) but inconsistent with the SSRF focus elsewhere.
- **N25** — `google_sync.py:142-148` `disconnect`: if `db.commit()` throws, the function propagates 500 and `SchedulerService.sync_google()` on `:148` never runs → stale recurring job pointing at a deleted account.
- **N26** — `web_clip_service.py:112-114` `_MAX_BYTES` truncates `resp.text` after httpx already buffered the entire body — a malicious page can force arbitrary RAM buffering before truncation. Low impact (loopback) but worth a streaming/Content-Length guard.
- **N27** — `ollama_service.py:446-456` `_parse_json_response` `start=min({)` / `end=max(})` heuristic can grab unrelated `{`…`]` and `}`…`]` boundaries. Today falls through to `return None` (safe) but fragile.
- **N28** — `main.rs:22-50` `check_deps` returns `"all_installed": ollama` — copy-paste bug; the field reports only the Ollama result, not the AND of all three checks. UI correctness in the Settings panel.
- **N29** — `main.rs:127-140` `reclaim_port` fallback `pkill -f lifelogr-backend` is broader than the web-deb's very specific match (`/opt/lifelogr/backend/.venv/bin/python -m uvicorn app.main:app`); could kill an editor/build script with `lifelogr-backend` in its args. Low (single-instance limits the scenario).
- **N30** — `build-web-deb.sh:438-444` `prerm` is a no-op (`true`). On `dpkg --remove` while running, the binary is deleted but uvicorn keeps serving from memory holding deleted file handles; once `/opt/lifelogr/bin/lifelogr --stop` is gone there's no clean stop. Replicate `preinst`'s stop logic.
- **N31** — `entries.py:162` `/export/markdown` writes `entries/{entry.entry_date}.md` per entry; `entry_date` is not unique → same-day entries silently overwrite each other in the zip (data loss on export).
- **N32** — `email.py:346` `upload_temp_attachment` does `await file.read()` before the `EMAIL_MAX_ATTACHMENT_SIZE_BYTES` check at `:347`. A streaming client can OOM the process before the cap triggers.

---

## Test coverage — verified gaps

CI gates ruff + strict-mypy + full pytest + frontend build + 3 Playwright specs on every PR and release tag. Solid for the category. **No coverage floor** (`ci.yml:36` runs `pytest tests/ -q` with no `--cov`/`--cov-fail-under`), so the untested paths below stay untested silently.

Specific verifications (4 fail, 4 pass):

| Critical path | Test? | Evidence |
|---|---|---|
| IMAP fetch+store loop (`email_service.py:469-678`) | **FAIL** | `grep sync_folder\|_store_message tests/` → 0 hits. `test_email.py:3` explicitly skips ("need a real mailbox"). MIME parse, UIDVALIDITY wipe, attachment persist, `.eml` write all unexercised. (AUDIT H1.) |
| `cloud_sync_service.push()` (upload half) | **FAIL** | `grep "\.push(" tests/` → 0 hits. `test_cloud_sync_pull.py` covers `pull` only. (AUDIT H1.) |
| OAuth state store (`oauth_state.py:22-43`) | **FAIL** | `grep OAuthStateStore\|oauth_state tests/` → 0 hits. 44 LOC, 4 live providers depend on it, zero tests. |
| note_media from-path denylist (`note_media_service.py:147-159`) | **FAIL** | `TestNoteMediaFromPath` has only happy-path + 404; the denylist (and AUDIT M1's missing entries) never directly exercised. A regression loosening it passes green. |
| SMTP send/save_draft | **FAIL** | `test_email.py:3` explicitly skips. (AUDIT H8.) |
| `security.py` v1→v2 reencrypt + wrong-key | **PASS** | `test_reencrypt_upgrades_v1_to_v2` + service-layer wrong-passphrase→400 tests. |
| Entry-level per-entry-salt encryption | **PASS** | `test_new_encryption_uses_random_per_entry_salt` asserts salts differ and are ≥16 bytes. |
| `web_clip_service` SSRF guards | **PASS** | 6 tests incl. redirect-to-internal and DNS-rebinding mock. Best-covered of the eight. |
| `atomic_restore` end-to-end rollback (`restore.py:219-227`) | **PARTIAL** | Pieces tested (`test_no_partial_on_failure`, `test_rollback_on_copytree_failure`); the full media-fail→roll-DB-back branch is not. (AUDIT H8.) |

---

## Templated / duplicated patterns

- **The 4 cloud OAuth routers (`box.py`, `dropbox.py`, `onedrive.py`, `google_drive.py`) are one AI-templated `oauth_callback` copy-pasted 4×** — ~400 LOC of structurally identical code (state consume → load creds → httpx post → build creds dict → encrypt → upsert BackupConfig → commit → render HTML). Every bug found in one (`tokens["access_token"]` outside try/except → bare 500, raw `str(exc)` in HTML, state-consumed-before-error) is duplicated 2-4×. Two different HTML-success-page styles exist across the four. A shared `oauth_callback_common()` helper would collapse this and stop per-file drift. This is *why* several of the low findings above are 4× bugs.
- **`encrypt(...)`+`flush()` in `sync.py:92` vs `reencrypt(...)` in `backup_service.py`** — cloud-provider construction triplicated, two paths persist credentials differently. (AUDIT M12.)

---

## Not a finding (explicitly cleared)

- **Email HTML rendering** is well-defended: `<iframe :srcdoc="…" sandbox="">` (empty `sandbox` = strictest possible) at `EmailView.vue:992, :1211`. A prior review flagged "no DOMPurify" — immaterial given the sandbox. The only hole is the print path (N5).
- **All other `v-html` sites** (7 of them) route through `DOMPurify.sanitize()`; SearchPalette correctly restricts to `ALLOWED_TAGS: ['mark']`. Clean.
- **Token storage**: no auth tokens stored client-side at all. CSRF N/A given the no-auth model.
- **CORE SQLite pragmas, FTS5 triggers, migration idempotency, `oauth_state.py`, `archive.py` tar extraction** (`filter="data"` + path-segment guard + resolve-before-contain) — all correct.
- **`build.sh`** — clean (`set -euo pipefail`, prereq checks, correct target-triple detection).
- **`memorial.py`** — subprocess uses `create_subprocess_exec` (no shell), `start_new_session=True`, proper SIGTERM→SIGKILL under lock. Clean.

---

## Recommended fix order for on-call handoff

1. **B1** (Tauri SECRET_KEY) — one-time fix, unblocks safe Tauri ship.
2. **N1** (email header injection) — one-line `_sanitize(att.filename)`.
3. **N2 + N3** (OAuth refresh rollback) — commit refreshed creds before push/sync.
4. **N4** (sync/import/storage-path concurrency lock) — one `asyncio.Lock` per path.
5. **N5** (printEmail XSS) — DOMPurify or srcdoc-in-print-window.
6. **B2 + N6 + N11 + N12** (atomicity family: backup, restore-backup, temp attachments, media delete) — these are the data-loss-at-3am class.
7. **Tests for IMAP loop, cloud `push()`, OAuth state store, note_media denylist** (H1 + the 4 FAIL rows above) — the untested paths most likely to silently drop data.

Everything else is real but won't page you at 3am.

**File references** (all absolute): the load-bearing ones are `/home/em/code/wip/diary/desktop/src-tauri/src/main.rs:262-272` (B1), `/home/em/code/wip/diary/backend/app/routers/email.py:280-282` (N1), `/home/em/code/wip/diary/backend/app/routers/sync.py:84-146` (N2), `/home/em/code/wip/diary/backend/app/services/google_sync_service.py:52-56` (N3), `/home/em/code/wip/diary/frontend/src/components/email/EmailView.vue:493-500` (N5), `/home/em/code/wip/diary/backend/app/core/restore.py:194-197` (N6), and `/home/em/code/wip/diary/backend/app/services/recording_service.py:43,113-122` (N7).
