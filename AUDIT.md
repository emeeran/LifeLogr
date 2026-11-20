# Production Readiness Audit — 2026-11-20

Six parallel audit dimensions (correctness/error-handling, security, config/environment,
observability, testing/CI, operational readiness), each independently verified with file:line
references. Post-cleanup state: cleanup/pipeline-2026-11-20 @ phase(3), all suites green
(backend 1067, frontend 360, ruff/mypy/eslint/vue-tsc clean).

## Summary

**Ready with fixes.** The architecture-level story is genuinely strong for a local-first
desktop app: PKCE OAuth with loopback-locked redirects, AES-256-GCM with fresh nonces and a
scrypt passphrase KDF, PEP-706 tar extraction with path-traversal rejection, DNS-rebinding
Host guards, hermetic gated CI (lint → strict mypy → tests with an enforced coverage floor →
e2e → version parity), boot-time DB integrity verification with snapshot quarantine, and
idempotent-by-construction scheduled jobs. No secrets, no injection paths, no unsafe
deserialization, no floating dependencies, and version sources agree exactly.

But there are **three high-severity data-integrity risks, all in the same family**: big
imports and the weekly integrity restore either freeze the event loop or swap the live
database under a running app, and the desktop shell's close guard interprets a
frozen-and-therefore-unreachable backend as "safe to kill". Individually each is an edge
case; together they can destroy (or revert) journal data in exactly the scenarios — crash,
corruption, restore — where the app most needs to be trustworthy. Fix these before the next
release. Everything else is medium/low polish.

## Blockers (must fix before next release)

- [ ] `backend/app/routers/entries.py:1391-1393` — **import path blocks the event loop and
  reads up to 2 GiB into RAM**: `parse_diarium_sqlite(upload_path)` (sync, unbounded SQLite
  fetchall) runs directly in the async handler; `upload_path.read_bytes()` loads the spooled
  upload (cap 2 GiB, `config.py:330`) before any format branch; zip member parsing is sync
  (members capped 64 MiB but unbounded in count). While blocked, `/health` and
  `/system/shutdown-state` stop answering, and the shell maps "unreachable ⇒ not busy"
  (`desktop/src-tauri/src/main.rs:688-689`) so a close during the window SIGTERM→SIGKILLs the
  sidecar mid-import — defeating the close guard. Fix: offload parse to a thread/job
  (`asyncio.to_thread` or move into the existing `as_job` path) and stream the spool instead
  of `read_bytes`. *(Found independently by both the correctness and operations audits.)*
- [ ] `backend/app/core/database.py:419-425` — **boot-snapshot skip fingerprint misses
  in-place writes**: the snapshot is skipped when `(st_size, page_count)` matches the newest
  snapshot, but same-length row edits (body edit, `is_deleted` flip) change neither. Every
  such day skips snapshotting, so "newest good snapshot" can be weeks old — and the
  corruption-recovery path restores exactly that. Fix: fingerprint on data (e.g. WAL
  salt/mtime, or always copy — snapshots are cheap relative to the risk).
- [ ] `backend/app/services/scheduler_service.py:805-848` → `core/database.py:438-480` —
  **weekly integrity restore swaps the live DB under running writers**: `_recover_from_snapshot_sync`
  unlinks the live file while pooled sessions hold fds; commits between unlink and
  `reinit_engine()` vanish into the orphaned inode. No quiesce, no post-restore re-check
  before reinit (unlike the boot path, which re-verifies). Fix: quiesce writers (or reuse the
  shutdown path), re-verify the restored file, then swap.

## High priority

- [ ] `backend/app/routers/backup.py` (media-only restore branch, ~459-461) — non-atomic
  `rmtree` + `copytree` of the live media dir on the event loop, unlike the DB path's
  `_atomic_media_swap` with rollback. ENOSPC/crash mid-copy loses attachments. Route through
  the atomic swap helper.
- [ ] `backend/app/routers/entries.py:1898-1909, 1150-1155` — per-record import failures log
  "skipped" but never `db.rollback()` after a partial flush; the half-built entry commits
  with the next batch, and a flush-time failure poisons the session for all remaining
  records. Roll back per failed record.
- [ ] `backend/app/main.py:448-470` — strict-origin guard gap: `POST /api/v1/settings` and
  AI-provider endpoints (which hold base_urls/API keys — the audit's named crown jewels)
  are covered only by the trust-any-loopback CSRF guard, so a hostile page on another
  loopback port can silently repoint an AI provider and exfiltrate journal text on the next
  enrichment pass. Add these prefixes to `_STRICT_ORIGIN_POST_PREFIXES`.
- [ ] `desktop/src-tauri/capabilities/default.json:20-21` — `fs:allow-read-file`/
  `fs:allow-write-file` granted with no `fs:scope` (verified against the generated ACL);
  any renderer compromise gets arbitrary file I/O. Add scopes or drop plugin-fs for the
  dialog use-cases the Rust `save_url_as`/`upload_file_as` commands already cover.
- [ ] No sweeper for `DATA_DIR/tmp` staging archives (`export_service.py:90`, `jobs.py:264`,
  `backup.py:283`, `backup_service.py:198`) — crash/SIGKILL mid-export orphans DB+media-sized
  files forever. Add a boot/scheduled sweep.
- [ ] `backend/app/services/media_service.py:213` — `spool_upload` writes to system `/tmp`
  (tmpfs = RAM) with no `dir=`; every upload up to 2 GiB goes through memory — the project's
  own documented OOM incident mode (`backup.py:282-284`, `export_service.py:79-85`). Spool
  under `DATA_DIR/tmp` instead.

## Medium priority

- [ ] `backend/app/services/ics_service.py:72-78,104` — one malformed ICS line (`DTSTART:2026-13-99`)
  500s the whole calendar sidebar; catch per-event and skip.
- [ ] `backend/app/services/backup_service.py:210-232` — a crash mid-cloud-upload leaves
  `backup_snapshots.in_progress` forever; the close guard then polls busy=true for the full
  120 s on every window close until a backup happens to run for that config. Boot-time
  reclaim sweep.
- [ ] Reminder catch-up predicate `_reminder_due_for_catchup` (`scheduler_service.py:1105`)
  has zero direct tests — it contains the documented tz-fix and weekday filtering, and a
  regression silently drops or double-fires offline reminders.
- [ ] `backend/.env.example` missing vars config reads: `WEATHER_ENABLED`, `MAP_ONLINE_TILES`
  (both = network egress toggles — the ones a privacy-focused install must know),
  `ENCRYPT_MEDIA`, `MAX_IMPORT_SIZE_BYTES`, `TTS_CACHE_DIR`/`WEATHER_CACHE_DIR`,
  `LIFELOGR_DATA_DIR` (highest-precedence data dir).
- [ ] `scripts/build-web-deb.sh:243-268` — port fallback off 18765 silently breaks all four
  cloud providers' fixed OAuth loopback redirect; surface or refuse the fallback.
- [ ] `backend/app/main.py:726-727, 764-766` — two more silent excepts in `/health`
  (scheduler + startup-checks blocks) violating the no-silent-except rule; the FTS one got
  fixed in phase 3, these two were missed.
- [ ] `backend/app/main.py:684-796` + `main.rs:688-689` — no event-loop liveness signal in
  `/health`; combined with "unreachable ⇒ not busy" this authorizes killing a hung-but-busy
  backend (see blocker 1). Also: FTS probe is a full `count(*)` scan and Ollama probe adds a
  ≤2 s call on every poll.

## Low priority

- `backend/app/routers/_oauth_helpers.py:223` — `tokens["access_token"]` indexed outside the
  guarded blocks; a 200-with-error-body from a provider 500s instead of the styled error page.
- `backend/app/services/importers/diarium.py:250-252` — UTC-ticks assumption undocumented and
  untested (cited doc `docs/diarium-format-analysis.md` doesn't exist); local-time ticks would
  shift entry dates by a day for non-UTC users.
- `backend/app/routers/tts.py:211-218` — sync chunk writes on the loop (responsiveness, not
  correctness); `.part` leftovers never swept and don't count against cache caps (`tts.py:232`).
- `desktop/src-tauri/capabilities/default.json:11-14` — shell-open allowlist accepts any
  http(s) URL; `main.rs` `save_url_as`/`upload_file_as` don't CRLF-escape webview-supplied
  strings (contained: loopback, trusted callers).
- `backend/app/core/security.py:47,96-99` — legacy v1 credential-key format accepted forever;
  short pre-upgrade SECRET_KEYs leave old tokens brute-forceable. Consider forced re-encrypt.
- `backend/app/services/media_service.py:325-330` — `filename="..."` unescaped for ASCII names
  (quote breaks the header; no injection — Starlette rejects CRLF).
- `tauri.conf.json` CSP `style-src 'unsafe-inline'` (common Vue concession).
- `backend/app/main.py:59` — startup banner omits `APP_VERSION`; `main.py:213` logs request
  start AND completion (doubles access-log volume on job polling).
- `frontend/src/main.ts:55-93` — toast-level caught errors never reach `reportClientError`,
  so save failures leave no durable trace once the 7 s toast expires.
- `backend/.env.example:9` — CORS example drops the Tauri origins; copying it into
  `DATA_DIR/.env` breaks the desktop app (config also loads that file).
- `backend/app/core/config.py:465-466` — `LIFELOGR_IN_CONTAINER` kill-switch for the
  production bind check is undocumented (deliberate, set by Dockerfile).
- `Makefile:30,34,37`, `ci.yml:27,113`, `build.yml:68` — `uv sync` without `--frozen` can
  re-lock against `>=` floors in CI/release builds.
- `frontend/playwright.config.ts` — local e2e not hermetic (`reuseExistingServer: true`
  against a dev backend on :8000 writes into the real data dir; CI pins it correctly).
- `frontend/vitest.config.ts` — no coverage gate (backend enforces 78%).
- `backend/tests/conftest.py:19` — temp data dir never removed (one leaked /tmp dir/session).
- `backend/app/core/database.py:532`, `startup_checks.py:446` — managed-run detection split:
  raw `DATA_DIR` env vs `_is_managed_run()` (which also honors `LIFELOGR_DATA_DIR`) can answer
  differently in the same run.
- `backend/app/main.py:172-179` — shutdown doesn't cancel Ollama `_PULL_TASKS`/TTS
  `_prewarm_tasks` (also never discarded, so the set grows unboundedly); `wait=False`
  scheduler shutdown can orphan a running backup job's `.part`.
- `scheduler_service.py:644-667` vs cron misfire — narrow double-notification race, no state
  corruption.
- `cloud_sync_service.py:127` — LocalFileProvider payloads accumulate under `/tmp` with no
  retention.

## Explicitly out of scope / accepted risk (flagged deliberately, not fixed)

- **Phase 2 declined refactors:** `AiDrawerPanel` vs `useAiTools` overlap (merging risks
  spec AI3/AI5 behavior; `callAiTool` already centralizes the mechanics); the truncation
  notice renders differently by design in drawer vs context menu; `SecurityPanel.downloadKit`
  hand-rolls its download — switching to `saveFile` would open a native dialog (observable
  change, needs a product call).
- **Web-deb ships `APP_ENV=development`** (`build-web-deb.sh:204-205`): rate limiting off and
  `/docs` exposed — accepted for loopback-only single-user; noted as a hygiene deviation.
- **Trust-any-loopback CSRF residual** (`main.py:337-355`): documented trade-off for the
  dynamic SPA port; destructive endpoints are carved out. The high-priority strict-origin gap
  above is the part worth tightening, not the whole design.
- **Known-fragile environment notes** (from project history): WebKitGTK renderer OOM class —
  all known webview-heavy paths were fixed 2026-11-19 (streaming transfers, /thumb, log
  rotation); new growth paths found here are the spool/tmpfs and tmp-sweeper items above.
- **Mobile/`docs/plans/PRD-mobile.md`** are untracked scaffolding, out of scope.

## Pipeline self-report

- Phases 0–3 committed on `cleanup/pipeline-2026-11-20` (baseline, purge, debloat ×4,
  formatting, style). Net phase-2 delta: −164 lines over 26 files; phase-3 formatting
  −271 lines of drift over 113 files.
- **The audit caught a regression this pipeline introduced**: the phase-2 backup-runner
  dedup left an unreachable duplicated sync branch in `run-now`
  (`routers/backup.py`) — found by the correctness audit, removed in commit `5abf130`.
- Prior cleanup pass (2026-11-17) blockers were not seeded into these audits; both were
  re-derived independently here (origin-trust family re-surfaced as the strict-origin gap
  and CSRF residual above).
