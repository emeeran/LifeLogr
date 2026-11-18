# Production Readiness Audit — pass 4 (2026-11-17)

Branch `cleanup/pipeline-2026-11-17`. Six parallel dimension audits
(correctness, security, config/env, observability, testing/CI, operations),
each finding-verified at file:line, reconciled against the pass-3 (2026-11-09)
audit. Baseline at phase 0: pytest 1031/2 stale-test failures · vitest 338 ·
ruff/mypy/vue-tsc/eslint/cargo check all clean.

## Summary

**Ready with fixes.** The core journaling paths are unusually well-hardened
(spool-with-cap uploads, PEP 706 tar extraction, atomic swaps, savepoint-batched
imports, PKCE OAuth, per-item scrypt KDF, PID-correct sidecar teardown, boot
corruption recovery) and both suites are green with real coverage of backup
round-trips, encryption, media caps, trash/purge, and exports. But this pass
found that the **close-time busy-guard — the mechanism that protects in-flight
imports/restores/backups from being killed at shutdown — is deterministically
defeated in every packaged desktop install** (three interlocking blockers
below), and the loopback origin-trust model has two bypasses that make the
destructive-origin guard ineffective against exactly the threat it was built
for. None of these are regressions from this pass; all predate it.

## Resolution status (fix wave 2026-11-18, branch `fix/audit-pass4`)

**Fixed** (commits on the fix branch; all gates green — pytest 1026, vitest
335, eslint, vue-tsc, cargo test, docs-check): all three blockers (limiter
exemptions, kind-prefix matching, offloaded restore I/O); the origin-port
bypass (same-origin now compares port); the AI-provider exfil backdoor
(confirm_remote required for non-loopback base_urls); the destructive-coverage
gap (second strict-origin tier for irreversible deletes + wholesale settings
ops, decoupled from the throttle); content-blind encryption tests; Settings-
backed env knobs; /health disk+writability probe; the shell's exact /health
contract match; honest Docker bind validation (BIND_HOST passed through,
container carve-out documented); Tauri capabilities narrowed (static fs
grants dropped — dialog runtime scope covers picked paths — unused
spawn permission removed, shell:allow-open scoped to http(s)); diarium
connection/spool leak; recordings spooling; import .md/.json 500s; dropped-
attachment logging; reminder misfire grace + naive-UTC catch-up; backup
export staged-file leak; request-id propagation; 5xx log level; APP_ENV
normalization; TTS prewarm GC guard; client-error shedding marker; port-
discovery failure reporting; doc-version drift (docs-check passes);
upload_file traversal guard; eslint covers the e2e specs; CI installs
tesseract (OCR tests unskip).

**Still open** — needs a design call or manual verification, deliberately
not guessed at:
- `_remap_media_urls` KeyError → committed-but-counted-skipped entries
  (needs the savepoint restructuring the audit sketched); frontend
  stale-response race cluster; BackupRestorePanel swallow; god-router split;
  Rust-shell test coverage (real design work, best with the pending manual
  GUI tasks in `docs/plans/pending-tasks.md`); settings e2e wiring asserts;
  vitest coverage instrumentation (attempted — npm 12 reify bug blocks the
  install; hand-editing the lockfile would be worse); LOG_LEVEL knob; CSP
  port pinning; Content-Disposition escaping; DNS-rebinding TOCTOU; web-deb
  /docs flag; port/Ollama-URL defaults duplication; PyInstaller `yaml`
  hidden-import; `.env.example` gaps (ENCRYPT_MEDIA etc.); close-guard
  unreachable⇒not-busy; web-deploy boot recovery runbook; `run_setup`
  spawn_blocking.
- **One manual GUI check owed by the capabilities change:** save-as and
  open-file dialogs must still work (the dialog plugin's runtime fs scope
  now backs them instead of static grants). Add to the manual pass in
  `docs/plans/pending-tasks.md`.

## What this pass changed (phases 0–3)

Net −795 lines across 60+ files, 11 commits. Removed the dormant `/sync` queue
machinery (~450 lines, providers kept — backup uses them); unified the four
OAuth callback flows into one reviewed helper (security review: no regressions);
canonical media-cap checks; shared VACUUM connection helper; four dead non-Linux
cfg stubs; dead frontend code (`errMsg`, `toggleDetailPanel`, `reset`,
test-only `clearAll`, SSR guards); dedup of `fail()` ×3 stores and 14 ad-hoc
catch-mappings onto `errorMessage()`; Playwright boilerplate → `tests/helpers.ts`;
two stale tag tests rewritten to the documented explicit-tags convention;
logging/style consistency (`exc_info` stragglers, dead comment refs, import
hygiene, `notes_router` collision, rustfmt). Two facts corrected in docs:
`.env.example`'s pool comment (knobs DO apply to SQLite) and the RemindersView
double-toast (store contract).

## Blockers (must fix before shipping a release)

These three interlock: any one alone leaves the close path unsafe during
long-running protected work.

- [x] `backend/app/main.py:240-241` + `desktop/src-tauri/src/main.rs:552` —
  **the production rate limiter 429s the shell's own shutdown polls.** The
  sidecar launches with `APP_ENV=production`, so `is_production` is true on
  every desktop install; `useJobProgress.ts:6` polls `GET /jobs/{id}` at 1 Hz
  and `main.rs:300-303` polls `/api/v1/system/shutdown-state` every 300 ms —
  neither path is exempt (media/thumbnails got an exemption, these didn't).
  After ~18 s of waiting, shutdown-state returns 429 whose parsed body has no
  `busy` → `unwrap_or_default()` reads "not busy" → the shell SIGTERMs and
  SIGKILLs the backend mid-restore/import. Also 429s real user actions during
  any long job. Fix: exempt the poll paths (`/system/shutdown-state`,
  `/jobs/*`) from the per-IP limiter, or scope the limiter to non-loopback
  mutators.
- [x] `backend/app/routers/system.py:30,112` — **the shutdown guard's
  job-kind allowlist matches none of the local/import job kinds.**
  `_SHUTDOWN_BLOCKING_JOB_KINDS = {"import","restore","backup"}`, but the
  kinds actually registered are `backup-local`, `restore-local`,
  `import-entries`, `import-notes-{kind}` (backup.py:100/145/177/193/269/386,
  entries.py:1093/1616, notes.py:522). The `BackupSnapshot.in_progress` check
  saves only cloud backups; the most destructive path — local restore's DB
  swap — reports `busy: false` and close kills it mid-swap.
- [x] `backend/app/core/restore.py:242-256,346` (via `routers/backup.py:440`)
  — **bulk sync file I/O on the event loop during restore.** `_atomic_write`
  (full DB copy) and `_atomic_media_swap` (`shutil.copytree` of the entire
  media dir) run inline, unlike their own callers which offload via
  `asyncio.to_thread` (backup.py:412/427). A multi-GB restore blocks the loop
  for minutes: `/shutdown-state` and `/health` stop answering, and the shell's
  "unreachable ⇒ not busy" path (main.rs:298-303) tears the backend down
  mid-media-copy, leaving a half-restored `media/` tree. Fix this before the
  two above are meaningful for restores.

## High priority

- [x] `backend/app/main.py:286-296,375-381` — **the destructive-origin guard
  is bypassable: the same-origin fallback compares hostname only, ignoring
  port.** The guard exists to stop "a hostile page on another local port";
  that example only works because `localhost` ≠ `127.0.0.1`. A page at
  `http://127.0.0.1:9999` passes (`Origin` host == `Host` host), reaching
  `POST /entries/reset` (full DB wipe), `/backup/import` (wholesale DB
  replacement), purges. Fix: compare scheme+host+port for destructive paths.
- [ ] `backend/app/main.py:299-312` + `routers/ai.py:493-497` +
  `schemas/ai_provider.py:43-53` — **any loopback page can plant a persistent
  journal-exfiltration backdoor with one request.** The generic CSRF guard
  trusts *any* loopback origin; `POST /ai/providers` accepts an arbitrary
  remote `base_url` with `is_active: true`; enrichment then auto-sends every
  entry body to that URL forever. Related gap: `settings.py:168-176` requires
  `confirm_remote` for a non-loopback `OLLAMA_BASE_URL` but providers have no
  equivalent gate (`_normalize_base_url` checks scheme/host only). Fix:
  require the remote-config confirmation for provider base_urls (this also
  closes the drive-by), and/or drop raw-loopback trust for provider writes.
- [x] `backend/tests/unit/test_encryption_service.py:32-41,104-147` — **the
  decrypt round-trip tests never assert restored plaintext** — only
  `status_code`/`is_encrypted` flags. A decrypt path returning garbage or
  dropping bodies would pass every encryption test. Assert the body equals
  the original after each decrypt (including the legacy/PBKDF2 migration
  fallbacks, whose own comments say "no entry may become undecryptable").
- [x] `backend/app/services/backup_service.py:48`,
  `enrichment_service.py:28,43`, `media_service.py:84,124` — **three
  env-documented knobs are read via `os.environ` and never load from `.env`**
  (no `load_dotenv` exists; pydantic-settings populates only `Settings`).
  `.env.example` documents `BACKUP_CLOUD_RETENTION`,
  `LIFEOGRF_ENRICHMENT_CONCURRENCY`, `MEDIA_IMPORT_ALLOWED_ROOTS` as `.env`
  entries — setting them there silently no-ops, and the packaged sidecar
  forwards only `DATA_DIR`/`APP_ENV`, making them unreachable entirely.
  Either route them through Settings or document them as export-only.
- [x] `backend/app/main.py` `/health` — still no data-dir writability or
  `shutil.disk_usage` probe (carried from pass 3; boot-time check only,
  `startup_checks.py:441`). A full/read-only volume stays "healthy" while
  every write 500s.
- [x] `desktop/src-tauri/src/main.rs:147-163` — `port_is_lifelogr` matches
  any response containing "200"/"ok" before `fuser -k`; any JSON API on the
  port gets SIGKILLed. Match the exact `/health` contract (carried).
- [ ] Docker/web variant: `Dockerfile` CMD hardcodes `--host 0.0.0.0` so the
  production bind guard validates the unchanged default; a bare
  `docker run -p 8000:8000` exposes the unauthenticated API on all interfaces
  while the guard passes. `docker-compose.yml` still passes dev `.env`
  wholesale (carried).
- [x] Destructive routes outside the strict origin guard — now larger than
  the pass-3 list: `DELETE /media/{id}`, recordings/video-note/note-media
  deletes, `DELETE /backup/snapshots/{id}` (carried), plus
  `POST /settings/storage-path` (hot-copies DB + media + `.secret_key` to an
  attacker-chosen path, `settings.py:348`), `DELETE /backup/schedule`
  (silently disables auto-backup, `backup.py:551`),
  `POST /settings/recovery-kit/import` (swaps the live key, `settings.py:314`),
  `/settings/vacuum`, `/settings/encrypt-media`, `POST /entries/import`
  (`main.py:348-364` guard vs these). Note the pass-3 tradeoff stands: the
  destructive guard couples origin strictness with a 5/60s rate limit that
  would break legitimate bulk deletes — decouple the two concerns.
- [x] `desktop/src-tauri/capabilities/default.json` — broad
  `fs:allow-read/write-file` over `$DOWNLOAD/$DOCUMENT/$PICTURE/$DESKTOP/
  $HOME/Documents` (only legitimate use is the user-picked save dialog,
  `utils/fileDialog.ts:29`) and `shell:allow-spawn args:true` (carried,
  verified unchanged this pass).

## Medium priority

**New this pass:**

- `backend/app/routers/entries.py:1261` — `KeyError` in `_remap_media_urls`
  for a body URL whose media didn't import (truncated zip, over-cap blob,
  signature-blocked). Worse, the per-entry `except` at :1912 doesn't roll
  back: the entry row + flushed media stay committed at the next chunk
  boundary while the entry is counted `skipped` — "imported 0" with rows in
  the DB. Fix together: leave unresolvable URLs untouched, and wrap the
  post-create section in its own `begin_nested()`.
- `backend/app/services/importers/diarium.py:149,295-298` +
  `entries.py:1406-1416,1576-1589` — corrupt `.diary` upload leaks the
  sqlite connection (close not in `finally`), leaks the multi-GB spool file
  (cleanup path unreachable on exception), and returns a raw 500.
- `backend/app/routers/recordings.py:29` — only upload endpoint using
  `await file.read()` before any size check (every other path uses
  `spool_upload`); a 20 GB body OOMs the sidecar.
- `backend/app/routers/entries.py:1549-1550,1533-1534` — malformed `.json`
  top level or a non-UTF-8 `.md` member 500s the whole import instead of a
  400 / per-file skip (sibling JSON branches handle this correctly).
- `backend/app/main.py:196-209` — request-id middleware generates the id but
  never propagates it (no contextvar, no response header, not in the
  unhandled-exception log) — correlation is nominal only.
- `backend/app/services/notes_export_service.py:334-335,355-356` — imported
  note attachments silently dropped on size-cap/malformed-ref with no log
  line: import finishes "successfully" with media missing and no trace.
- `backend/app/services/scheduler_service.py:1010` vs `:519-528,977` —
  reminder catch-up treats naive-UTC `last_fired_at` as local time;
  `.astimezone()` assumes local. The identical bug was diagnosed and fixed
  for backups; not carried to reminders → duplicate notification on restart
  in timezones where UTC/local dates diverge at fire time.
- `backend/app/main.py:201-208` — all responses (incl. 5xx) logged at INFO;
  failure triage by level impossible.
- `frontend/src/main.ts:104-105` — `get_backend_port` failure falls back to
  the default port with only a `console.warn`; in a packaged webview that's
  invisible — exactly the squatter scenario the shell hardens against.
  `reportClientError` is in scope and unused here.
- Temp-file leak paths: `routers/backup.py:286-308` (`/backup/export` staging
  created before `checkpoint_wal`/`_pack`, unlink registered only on
  success) and `core/jobs.py:188-193` + `routers/jobs.py:39-43` (result-file
  cleanup `except OSError: pass` — every failed unlink leaks a multi-MB
  file in `DATA_DIR/tmp` unlogged).
- Vitest runs with no coverage instrumentation or floor (backend has 78);
  `frontend/package.json` lacks `@vitest/coverage-*`.
- `backend/tests/unit/test_ocr_service.py` skips entirely in CI (no
  tesseract on runners); one `apt-get install` line closes it.
- `main.rs:120-123` — `run_setup` blocks a tokio worker on interactive
  `pkexec .output()` (should be `spawn_blocking`; the file's own rule).

**Carried from pass 3 (re-verified present):**

- Media writes go straight to final paths, no temp+rename
  (`note_media_service.py:112,179-185`, `media_service.py:443,502-504`,
  `video_service.py:60,103`) — ENOSPC mid-write leaves truncated orphans.
- No free-space checks before backup/restore/export staging; no boot sweep
  for orphaned staged artifacts in `DATA_DIR/tmp`.
- `routers/media.py:69-90` batch upload: per-file commits, no per-file
  results — one bad file errors the batch ambiguously; retry duplicates.
- `main.rs:242-246` `pkill -f lifelogr-backend` fallback can kill unrelated
  processes matching the substring.
- `capabilities/default.json:7` bare `shell:allow-open`, no URL validation.
- `main.rs:39-44` + `tauri.conf.json:25` — `DIARI_PORT` legacy env override
  honored but CSP pins `127.0.0.1:18765`; non-default port silently breaks
  the webview's API reach.
- `frontend/src/utils/markdown.ts:60-61` — `data-enc` attr unescaped
  (escAttr unused in-file); DOMPurify is the backstop.
- `BackupRestorePanel.vue:489-503` — disabling auto-backup swallows a failed
  schedule DELETE; switch shows off while backups continue.
- `frontend/src/stores/tts.ts` has zero tests; no frontend coverage at all.
- `backend/app/main.py:609-611,614-670` — /health DB failure logs ~30
  duplicates per failed boot (2 Hz client polling); soft-check failures
  never logged.
- `Dockerfile:10,15` — floating `uv:latest`; `uv.lock` never COPYed.
- Reminder catch-up double-fire window + `_reminder_due_for_catchup` ignores
  its `now_utc` param (scheduler_service.py:640-662,988-991) — related to
  but distinct from the naive-UTC item above.
- Stats cache not invalidated on media mutations (60s TTL staleness).
- `scheduler_service.py:598-604` — reminder cron jobs use APScheduler
  defaults (1 s misfire grace; backup jobs get 3600); catch-up runs only
  once at boot → a blocked fire instant silently drops the reminder for the
  week.
- `main.rs:377-397` — close guard treats unreachable/timed-out backend as
  "not busy" (mitigated by `.part` + atomic replace; lost run, not loss).
- `database.py:389,398` — boot corruption auto-recovery is desktop-only
  (`DATA_DIR` gate); web/Docker deployment fails fast with no runbook.

## Low priority

**New:** `/recordings` prewarm task held by no strong reference, GC-able
(`tts.py:448`; the codebase guards this elsewhere, ai.py:280) ·
client-error rate-limit shedding leaves no marker on either side
(`system.py:73-74`, `clientErrors.ts:54`) · no `LOG_LEVEL` knob; logging
hardcoded at import (`main.py:42-46`) · TTS cache eviction skips unremovable
files then reports wrong-cap success (`tts.py:243-245`) · CSP
`connect-src http://127.0.0.1:*` + `style-src 'unsafe-inline'` — future
markup slip gets recon/exfil against all local services
(`tauri.conf.json:25`) · `Content-Disposition` filename not quote-escaped
(`media_service.py:324-331`) · web-clip SSRF guard has a DNS-rebinding
TOCTOU (`web_clip_service.py:64-100`) · web-deb ships `APP_ENV` unset →
`/docs` enabled (`build-web-deb.sh:205`, deliberate for rate-limit reasons —
decouple the docs flag) · port `18765` defaulted in four places
(`config.py:278`, `client.ts:11`, `main.rs:52`, `build-web-deb.sh:255`) +
legacy `DIARI_PORT` name in no docs · frontend AITab.vue:280 hardcodes the
default Ollama URL · PyInstaller spec hidden-imports `yaml` which no
dependency provides (`pyinstaller.spec`) · `.env.example` missing
`ENCRYPT_MEDIA`, `MAX_IMPORT_SIZE_BYTES`, `LIFELOGR_DATA_DIR` · eslint
doesn't cover `frontend/tests/` (`package.json:13`) ·
`scheduler_service.py:1010` naive-UTC duplicate-fire (promoted to Medium
above, kept here for the notification-only framing).

**Carried:** bulk dedupe bypasses semantic-cache drop
(`entries.py:995-1009`) · search `q` unbounded (`search.py:22`) ·
clipboard-denial toast spam (`EntryEditor.vue:1066-1075`) · embedding
backfill failure logs at DEBUG (`semantic_cache.py:352`) · keystrokes
typed during a CREATE round-trip erased on id-change reload (autosave
residual, pass-3 blind review) · frontend stale-response race cluster ·
`edge-tts` floor differs between deps and the `tts` extra
(`pyproject.toml:17` vs `:31`).

## Explicitly out of scope / accepted risk

- `trash2review/` — holding pen from passes 1–4 (now includes the sync
  model + its test file). Nothing hard-deleted; see its README. Zero live
  references verified this pass.
- Phase-2/3 refactors flagged, not applied: import-media attach-block dedup
  (2 sites, drifted — `entries.py:1266` vs `notes_export_service.py:318`);
  export-only-for-test seams (noteColors/changelog/aiToolRegistry/
  markdownMedia); logo duplication (`assets/lifelogr-logo.png` ≡
  `frontend/public/logo.png`, both build paths depend on their copy);
  `backup.ts` store-error contract internally inconsistent (swallow vs
  rethrow per method — needs a design call, caller-visible either way);
  `from __future__ import annotations` present in 80 files, absent in 27
  (Pydantic annotation-resolution risk if blanket-added);
  `_oauth_helpers.py`/`cron_utils.py` suffix names (rename only if touched).
- ruff format deliberately NOT imposed: 106/112 backend files are
  hand-formatted; lint-only is the convention.
- Renderer heartbeat watchdog (BLANK-7) — deferred by design, needs its own
  small design doc (`docs/plans/pending-tasks.md`).
- `/api/v1/sync` — parked since pass 2; service machinery removed this pass
  (providers kept; recoverable from git/trash2review).
- Flaky `test_ai_system_prompt` (failed once at phase-0 baseline, never
  reproduced — pure MockTransport tests, no clock usage; watch it).
- Untracked personal dirs (`assets/local/`, `assets/releases/`) and the
  user-managed `.env`.

## Missed by pipeline, caught by blind review

The phase-5 blind review (sanitized dispatch, full report verbatim in
`.pipeline/blind-review.md`) found five things the six dimension audits
missed, each re-verified in the main thread before being listed here:

- [ ] **`make docs-check` fails on the current tree** — README.md:9,97,107,
  docs/ARCHITECTURE.md:7,166, docs/manual/USER_MANUAL.md:7,52,61 all say
  0.16.0 while every version source says 0.17.7; the gate built to catch
  exactly this (Makefile:80-91) is red right now. The config auditor ran
  `check_version.py` (passes) but nobody ran `docs-check`. Cheapest fix in
  this entire audit.
- [ ] `backend/app/services/cloud_sync_service.py:153` —
  `LocalFileProvider.upload_file` builds `self._base / path` directly,
  skipping the `_safe_target` traversal containment every sibling method
  uses (upload/download/delete/download_to_file all go through it); it also
  returns an absolute path where `download_to_file` returns the relative
  input. No current caller passes user-influenced paths, but it's the one
  provider method that silently drops the guard.
- Rust shell is the least-tested code in the repo: `main.rs:1088-1114` is
  the entire test suite — 3 assertions on `health_ok` — while
  `reclaim_port`/`classify_port_owner`/`verify_sidecar_owner`/`begin_shutdown`
  (~900 lines owning process lifecycle, and the site of past incidents per
  its own comments) have zero automated coverage. The testing/CI audit
  scoped itself to pytest/vitest/Playwright and never looked at Rust.
- `backend/app/routers/entries.py` is a 2175-line god-router mixing entry
  CRUD, exports, the DB reset endpoint, and all import machinery (including
  note-domain helpers) — a structural smell no audit dimension covered.
- `frontend/tests/settings.spec.ts:20-147` asserts only static labels; the
  app's most destructive surface (Data tab: reset/import/restore) could
  lose its wiring and e2e stays green (entries.spec.ts:5-9 says so itself).

Also corroborated (higher confidence — both passes hit them independently):
the `DATA_DIR/tmp` boot-sweep gap and the export fail-path never unlinking
(`core/jobs.py:263-265`), the `pkill -f` fallback, and the rate limiter's
environment-dependence (dev never runs it, so blocker 1 is unreproducible
outside the packaged app — worth knowing when testing the fix).

New lows from the blind review, verified: `APP_ENV` test-environment checks
spelled three ways (`security.py:36` normalizes, `main.py:447` and
`recovery_kit.py:86` repeat the tuple inline, `enrichment_service.py:274`
uses a bare `== "test"` — so `APP_ENV=TESTING` fails the backfill guard
open, firing real network calls in a test session), and `_ollama_probe` is
an unlocked module global (`main.py:562-581`), inconsistent with the mutex
discipline used elsewhere.

### Open disagreement, surfaced for human adjudication

The blind reviewer's verdict — "would take on-call as-is, nothing blocker or
high" — directly conflicts with this audit's three blockers and two origin-
trust highs. Read the chains, not a headcount: the blockers live in
*cross-component* interactions (sidecar sets `APP_ENV=production` × limiter
skips dev × 300 ms shutdown-state polls; job-kind registry values × the
allowlist constant; event-loop-blocking restore × "unreachable ⇒ not busy").
The blind reviewer verified each component individually but did not trace
those chains. Tellingly, its security section praises the two-tier origin
guard as a strength — the same guard whose hostname-only comparison and
loopback trust this audit's security audit broke (its two highs) — and it
did not examine the shutdown-state polling path at all. Both reviews agree
on the component-level quality and on the `DATA_DIR/tmp` leak being the
most user-biting single issue. Resolution: treat the three blockers as
blockers until each is either fixed or disproven by hand; the blind
verdict is a fair description of the code *in the steady state*, this
audit's is a description of the *close-time failure windows*.

## Verification note

Every finding above was verified by the auditing subagent reading the cited
code, and the Blockers/High anchors were re-checked in the main thread
(`system.py:30`, `main.py:240/286/299/375`, `restore.py:242/346`,
`main.rs:552`, `capabilities/default.json`); the blind-review additions were
re-verified the same way (docs-check exit, `upload_file`, `APP_ENV` sites,
`_ollama_probe`). Honest limits: the six auditors and the blind reviewer all
run on the same underlying model, so this pass removes self-grading and
framing bias but not model-level blind spots — the origin-guard bypasses
were found by a prompted dimension audit and *missed* by the unprompted one,
which is exactly why both signals are recorded rather than averaged. A
fresh-session human review remains the strongest available check.
