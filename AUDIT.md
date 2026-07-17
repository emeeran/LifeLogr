# Production Readiness Audit — 2026-07-12

Branch: `debloat`. Source: 4 parallel read-only subagent audits
(correctness/error-handling, security, config+ops, observability+testing/CI),
each verifying findings against the actual code and self-correcting false
positives. Line numbers reflect post-Phase-3 state.

## Summary

**Verdict: ready for its intended use (local-first single-user app), with
fixes recommended before any broader/hosted deployment.** There are **zero
blockers** per the four-dimension audit. There are several **HIGH** issues;
most fall into two clusters: (a) input-validation gaps on two upload endpoints
(arbitrary local file read, unvalidated video upload) and (b)
resource/idempotency gaps in the new email subsystem (disk leaks, sync
double-fire). The crypto findings (deterministic salt, SECRET_KEY default) are
real but their blast radius is bounded by the local single-user model. None of
the HIGHs prevent the app from running; they are correctness/robustness/
hardening debts.

> **Important — see Reconciliation below:** the Phase 5 blind review
> independently surfaced a **CRITICAL** this audit missed — encrypting an
> entry indexes its **ciphertext into the FTS5 search index** and ships
> ciphertext to the LLM for enrichment — which elevates the encryption cluster
> above what the HIGHs below convey. Treat that as the single highest-priority
> item to fix.

## Resolution status (2026-07-12 — commits `5b82e22`..`b44e1b1`)

All CRITICAL/HIGH correctness, security, and crypto findings have been fixed;
297 backend tests pass, frontend build green. Remaining items are additive
test-coverage and lower-severity hardening.

**Resolved**
- CRITICAL ciphertext-in-FTS + HIGH ciphertext-to-LLM (`5b82e22`) — FTS triggers
  exclude encrypted entries (encrypt/decrypt toggle triggers); enrichment +
  on-this-day/themes skip encrypted entries.
- HIGH deterministic PBKDF2 salt → per-entry random salt w/ legacy read-compat (`e758438`).
- HIGH decrypt wrong-passphrase 500 → 400 (entry + note) (`5b82e22`).
- HIGH `notes/from-path` arbitrary file read → sandboxed to `$HOME`+temp, sensitive dirs denied (`ebdd711`).
- HIGH video upload zero validation → size + MIME + magic-byte checks (`ebdd711`).
- HIGH contact-photo magic bytes (`ebdd711`).
- HIGH email-sync double-fire → cross-job `asyncio.Lock` + `max_instances=1` (`6b0e8a8`).
- HIGH deleted-email disk leak (unlink on delete) + temp-attachment TTL GC + inbound attachment size cap (`3bf70d4`).
- HIGH (blind) `OLLAMA_BASE_URL` SSRF → scheme validated (`25ebe0e`).
- HIGH (blind) OAuth reflected-XSS → `html.escape` on error detail (`25ebe0e`).
- HIGH (blind) `get_db()` global lock removed (`8d5f52c`).
- MEDIUM (blind) `LocalFileProvider` path traversal → containment (`25ebe0e`).
- MEDIUM `_append_to_special` logs at WARNING; `RATE_LIMIT` wired to config; STARTTLS failure warns (`8d5f52c`).
- HIGH `.env.example` documents OAuth/email vars; SECRET_KEY default warns at startup (`b44e1b1`).

**Remaining (not in this pass)**
- HIGH **additive test coverage**: `email_protocol` MIME parsing, planner
  `_expand_recurrence`, contact vCard parse/serialize still lack unit tests.
  These are new tests, not bug fixes — recommended next.
- MEDIUM backup cloud-path RAM buffering (stream the gzip); lifespan draining of
  background email tasks (task registry); `/health` liveness/readiness split;
  `decrypt-text` bare-except narrowing; cloud `httpx` timeouts; AI-endpoint
  fake-success narrowing.
- LOW items (SPA containment guard, soft-delete guard on media parent, FTS-fallback
  surfacing) — defence-in-depth, low severity.

`SECRET_KEY`: auto-rotation was **intentionally not** done (it would break
already-encrypted credentials); the launcher already generates strong keys, and
the new startup warning surfaces any non-launcher run still on the default.

## Reconciliation with the Phase 5 blind review

A context-blind reviewer (no knowledge that a cleanup ran) caught real issues
the four-dimension audit missed, and vice-versa. Per the pipeline these are
logged here rather than silently folded into the earlier sections.

### Missed by pipeline, caught by blind review (genuine audit misses)
- **CRITICAL — `encryption_service.py:58` + `core/database.py:486` — encrypting an entry indexes its CIPHERTEXT into the FTS5 search index.** `encrypt_entry()` sets `entry.body` to base64 ciphertext and commits → the `fts_entry_au` trigger re-indexes that ciphertext. The search service doesn't filter `is_encrypted`. Result: search over encrypted entries matches/snippets ciphertext, and the plaintext is lost from the index even after decryption unless the entry is re-edited. (Notes too, via `fts_note_au`.) The pipeline audit read both files but never connected them. **Highest-priority fix.**
- **HIGH — `entry_service.py:42,106` + `routers/ai.py:149` — encrypted entries ship ciphertext to the LLM.** `create`/`update` call `EnrichmentService.schedule(title, body)` with no `is_encrypted` guard; `/on-this-day` slices `e.body[:500]` without the guard. Editing an encrypted entry sends its ciphertext to Ollama for embeddings/sentiment/summary.
- **HIGH — `routers/settings.py:210` — `OLLAMA_BASE_URL` is user-settable via the unauthenticated `PUT /settings`** → any caller redirects all AI features (which proxy journal content) at an arbitrary host: SSRF + data-exfiltration primitive. The pipeline's security pass checked OAuth URLs were hardcoded but missed this user-controlled one.
- **HIGH — OAuth callback error pages reflect exception text into HTML unescaped** (`google_drive.py:124`, mirrored in `box/onedrive/dropbox`): `_render_error_page` does `.replace("{{DETAIL}}", f"Failed to exchange code: {e}")` — `httpx` error text embeds the remote response body, an attacker-influenced reflected-XSS sink (low impact on loopback, exploitable if ever bound to `0.0.0.0`).
- **MEDIUM — `core/database.py:57` — `get_db()` wraps every request's session creation in a global `async with _engine_lock` and releases it immediately**, serializing all requests at lock-acquire for no benefit (SQLite's pool_size=1 already serializes). Avoidable throughput ceiling.
- **MEDIUM — `email_service.py:620` — synced inbound attachments are written to disk with no size cap** (the 25 MB limit is only enforced on the upload path, not on inbound mail).
- **MEDIUM — `cloud_sync_service.py:114` — `LocalFileProvider.upload(path)` joins a raw, partially user-influenced path with no normalization** — a latent path-traversal sink, currently dev-only but exported alongside the production providers.
- **MEDIUM — AI endpoints return fake-success (HTTP 200 with empty/canned content) on any exception** (`ai.py:202`, `ollama_service.py` parse failures) — silent AI failures look healthy to monitoring.

### Both agree (higher confidence)
- Deterministic PBKDF2 salt (`encryption_service.py:33`) — CRITICAL/ HIGH in both.
- `SECRET_KEY` default encrypts real credentials when the prod guard is bypassed (`config.py:127`) — both.
- Email-sync job overlap / missing `max_instances` (`scheduler_service.py`) — both.
- `_TEMP_ATTACHMENTS` unbounded leak; deleted-email disk-file leak; IMAP side-effects swallowed at DEBUG — all flagged by both.

### Caught by pipeline, not emphasized by blind review (still valid)
- The two upload-validation HIGHs (`notes/from-path` arbitrary file read; `video_notes` zero validation) — the blind reviewer didn't reach those services.
- Contact-photo magic-byte gap; `.env.example` missing OAuth/email vars; backup-in-RAM; lifespan not draining background tasks; the test-coverage HIGHs (`email_protocol`, planner recurrence, contact vCard) and the `test_encryption_service` `try/except:pass` hiding a 500.

### Honest limit
The blind reviewer runs on the same model as this session; the sanitized pass
removed self-grading/framing bias (which is why it caught the misses above) but
not model-level blind spots. The strongest independent check is a fresh
session / different reviewer. See `.pipeline/blind-review.md`.

## Blockers (must fix before prod)
- _(none)_ — consensus across all four audit dimensions.

## High priority

**Input validation (trust boundaries):**
- [ ] `backend/app/services/note_media_service.py:125` + `routers/notes.py:218` — `POST /notes/{id}/media/from-path` reads **any absolute path** the client sends (`Path(path).expanduser().read_bytes()`) and serves it back via the media endpoint. Arbitrary local-file disclosure (e.g. `~/.ssh/id_rsa`, the app's `.secret_key`). Intended for Tauri drag-drop but unauthenticated + unsandboxed.
- [ ] `backend/app/services/video_service.py:31` + `routers/video_notes.py:18` — video upload has **no MIME check, no magic-byte check, no size limit** (unlike `MediaService`/`NoteMediaService`, which enforce all three). Disk exhaustion + arbitrary-content storage served back as `video/mp4`.

**Crypto / key material:**
- [ ] `backend/app/services/encryption_service.py:32` — entry-encryption PBKDF2 uses a **deterministic salt** derived from the passphrase, not a random per-entry salt. Defeats the purpose of salting (no precomputation/rainbow-table protection). Store a random 16-byte salt per entry alongside the ciphertext.
- [ ] `backend/app/core/config.py:127` — `SECRET_KEY` defaults to `"change-me-before-production"` and the production guard is bypassed for the desktop sidecar / dev, so real IMAP/SMTP/cloud-OAuth credentials get encrypted (via HKDF from SECRET_KEY) under a publicly-known string. Generate a random per-install key on first run and persist it locally (the `.deb` launcher already does this; other run paths do not).

**Email subsystem (new on this branch):**
- [ ] `backend/app/services/scheduler_service.py:241,598` — `email_sync_boot` (one-off) and `email_sync` (interval) are **different APScheduler job IDs**, so `max_instances=1` does not prevent them overlapping → concurrent IMAP logins + interleaved flushes against single-writer SQLite → "database is locked" risk. Add a cross-job lock or shared job ID.
- [ ] `backend/app/services/email_service.py:60` — `_TEMP_ATTACHMENTS` (in-memory dict) + on-disk `_temp/` files have **no expiry/GC**; an abandoned compose leaks memory + disk forever.
- [ ] `backend/app/services/email_service.py:807` — deleted email messages orphan `.eml` + attachment files on disk (comment says "GC later" but **no GC exists**). Disk grows with every deletion.

**Testing gaps on untrusted-input / complex logic:**
- [ ] `backend/app/services/email_protocol.py` — **zero unit tests** for MIME parsing (`parse_message`), address decoding, snippet extraction, `ImapClient`. This is untrusted RFC822 input from arbitrary mail servers.
- [ ] `backend/app/services/planner_service.py:250` — **zero unit tests** for `_expand_recurrence` (dateutil rrule; DST/EXDATE/timezone edge cases). A malformed RRULE silently yields no occurrences.
- [ ] `backend/app/services/contact_service.py` — hand-rolled vCard parse/serialize (`parse_vcard:84`, `serialize_vcard:214`) has **no unit tests**; a malformed import could lose contacts silently.
- [ ] `backend/tests/unit/test_encryption_service.py:41` — wraps an assertion in `try/except: pass`, accepting either 400 **or an unhandled 500**. This hides a real bug: `routers/encryption.py:88` `decrypt_note` lets `InvalidTag` propagate (no try/except, unlike the entry-level path at :122) → 500 on a wrong passphrase.

**Config:**
- [ ] `backend/.env.example` — missing all OAuth + email-sync env vars (`GOOGLE_CLIENT_ID/SECRET`, `ONEDRIVE_*`, `DROPBOX_*`, `BOX_*`, `EMAIL_SYNC_*`). An operator deploying the `.deb` has no map of what's configurable.

## Medium / Low

**Medium**
- `email_service.py:1101` — after a successful SMTP send, the APPEND to the Sent folder is swallowed at DEBUG; the sent mail is not retained server-side yet `send()` returns `success: True`. (flagged by 3 agents)
- `email_service.py:794` / `:836` — IMAP flag-push and bulk-delete failures swallowed at DEBUG → local DB and IMAP server silently desync; the user's action can revert on next sync.
- `contact_service.py:642` + `routers/contacts.py:183` — contact photo upload checks size + extension but **not magic bytes** (cf. `MediaService` which blocks MZ/ELF/`<script`/`<?php`).
- `email_service.py` (sync) — inbound email attachments stored with **no type/magic/size filtering** (unlike the media-upload path).
- `backup_service.py:90` — cloud-backup path buffers the entire DB+media into RAM as one gzip (local path streams). OOM risk on low-RAM machines with large media libraries.
- `main.py:52` — lifespan shutdown does not drain the fire-and-forget background email tasks (`push_flags_background`, `move_to_trash_background`, …); a SIGTERM mid-IMAP-round-trip can leave server + local DB inconsistent.
- `main.py:279` — single `/health` conflates liveness + readiness and opens a DB connection per hit; no cheap `/healthz` split.
- Background email side-effects + `_reschedule_jobs` failures logged only at DEBUG, never surfaced to user or `/health` → a dead sync schedule looks healthy.
- `routers/encryption.py:126` — `decrypt-text` catches bare `Exception` → wrong-passphrase and server bugs return the same message with no logging.
- `core/config.py:181` — `RATE_LIMIT` env var is parsed but **never used** (hardcoded in `main.py:160`); misleading operator-facing config.
- `email_protocol.py:331` — opportunistic STARTTLS swallows all failures then logs in (possibly in plaintext) with no warning.
- `core/security.py:16` — HKDF for v2 credential key uses a static salt/info; fine only if SECRET_KEY is random per-install (see HIGH above).
- `storage_service.py:159` — DATA_DIR relocate `copytree` of MEDIA_DIR is non-atomic; a crash mid-copy can leave the target partial (DB validated, media not).
- CI: `.github/workflows/ci.yml:60` e2e job doesn't depend on the backend test suite; `.github/workflows/build.yml` builds installers with **no test gate** (a tag push bypasses CI).
- `pyproject.toml:7` — backend deps floor-pinned (`>=`); reproducibility relies on `uv.lock`/`--frozen`.

**Low**
- `main.py:365` — SPA catch-all joins `full_path` without an explicit `.resolve().is_relative_to(_FRONTEND_DIST)` containment guard (StaticFiles normalises `..`, so low risk; defence-in-depth).
- `media_service.py:77` / `recording_service.py:88` — parent `Entry` fetched without `is_deleted` guard → media can attach to a soft-deleted (invisible) entry.
- `entry_service.py:245` / `note_service.py:240` — FTS→ILIKE fallback masks a persistently broken search index (only a warning).
- `cloud_sync_service.py:150` — provider `httpx.AsyncClient()` has no timeout → spurious failures on large encrypted backups.
- Frontend has no unit/component test runner (only one Playwright e2e spec); ~0 store/component coverage.
- `core/config.py:126` — `APP_ENV` defaults to `development` on the `.deb` → `/docs` (Swagger) is reachable by anyone on the port.

## Explicitly out of scope / accepted risk

- **No auth on endpoints** — by design for the local single-user model (see `docs/04-design/ADR/002-no-auth-local-endpoints.md`). Not flagged.
- **OAuth success/fail page emoji** (`📦🎉❌✅` in `routers/{onedrive,box,google_drive,dropbox}.py`) — intentional product UX, not code voice.
- **AES-GCM + nonce handling, OAuth state tokens, backup tar traversal hardening, SQL/ORM parameterisation, shell-arg subprocess calls** — all verified sound; not flagged.
- **`SECRET_KEY` launcher path** — the `.deb` launcher generates a strong key with `secrets.token_hex(32)`, persists it `umask 077`, reuses across restarts. The HIGH above concerns *non-launcher* run paths.

## What's done well (for balance)
- `/health` degrades gracefully per-subsystem and returns 503 when the DB is down.
- Backup jobs are genuinely idempotent (`coalesce`, misfire grace, DB-level "in progress" guard + stale-run reclamation) and WAL checkpointing is robust.
- Encryption uses AES-256-GCM with HKDF-SHA256 + a versioned ciphertext format.
- Email sync is idempotent on `(folder, uid)`; cloud providers all close clients in `finally`.
- Tests are hermetic (mocked Ollama/httpx, fail-fast IMAP host, tmp-path schedule store).
- Request/response logging middleware with `req_id`; global exception handler logs stack traces; `.env` gitignored, no secrets in tracked source.
