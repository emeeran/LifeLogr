# Production Readiness Audit — 2026-11-08

Second cleanup-pipeline pass. Replaces the 2026-10-27 audit (all its items
were resolved; see git history for that document). Six dimensions audited
independently: correctness/error-handling, security, config/environment,
observability, testing/CI, operational readiness.

## Summary

**Ready with fixes.** The security posture, config hygiene, and observability
remain strong (injection/SSRF/crypto/secrets all verified clean; CI genuinely
gates releases). But this pass surfaced two data-integrity problems the prior
audit missed, both in the app's own safety machinery: **entry soft-delete
irreversibly destroys attachments at trash time**, and **scheduled local
backups can be killed mid-write by the shutdown guard and are written
directly to their final filename** — meaning the backup you keep may be
truncated and the trash you trust isn't trash. Neither is a crash; both are
silent, and both contradict the app's stated semantics. Fix those two before
calling the data-safety story done.

## Blockers (must fix before prod)

- [ ] `backend/app/services/entry_service.py:302-332` — **soft-delete
  hard-deletes all media + voice recordings immediately at trash time** (files
  unlinked; `VoiceRecording` rows cascade away via `models/recording.py:30`).
  `restore()` recovers only text; the notes flow keeps attachments and is
  lossless, so entries and notes have contradictory trash semantics, and the
  restore endpoint (`routers/entries.py:1033`) has no frontend caller. A user
  tapping delete expecting trash loses photos/audio permanently. Either defer
  media cleanup to purge (matching notes) or warn loudly in the UI.
- [ ] `backend/app/services/scheduler_service.py:761-834` — **scheduled local
  backups are invisible to the shutdown guard and written directly to their
  final filename.** `_run_backup` registers no job-registry entry and no
  in-progress `BackupSnapshot`, so `GET /system/shutdown-state` reads "not
  busy" and the desktop shell SIGTERMs (2 s) → SIGKILLs (2.5 s) mid-tar; and
  `tarfile.open(archive_path, "w:gz")` writes straight to
  `lifelogr-backup-<ts>.tar.gz`, leaving a truncated archive that retention
  counting still glob-counts. Cloud backups stage via mkstemp + in-progress
  row and are protected — the local path needs the same staging + registry
  entry (`.part` + `os.replace`).

## High priority

- [ ] `backend/app/main.py:363` + `backend/app/routers/backup.py:345` —
  `POST /api/v1/backup/import` is a multipart simple-request (no CORS
  preflight) and is absent from `_DESTRUCTIVE_PATHS`, so a hostile page on any
  other loopback port can swap the live DB — including the `settings` table,
  letting it re-point AI `base_url`s and harvest stored API keys on the next
  AI call. Add it (and `/restore`) to the strict-origin/destructive guard
  that `/entries/reset` gets.
- [ ] `backend/app/routers/entries.py:197-204,176-177,253,255,512-514` —
  malformed query/path params (`month=13`, `year=0`, `start_date=oops`) raise
  `ValueError` → generic 500 instead of 422; `tag_ids` parsing
  (`entries.py:182`, `search.py:31`) 500s on `?tag_ids=abc`. Type the params
  (`Query(ge=…)` / `date`) the way `search.py:23-24` already does.

## Medium priority

- [ ] `frontend/src/composables/useAutoSave.ts:101-139` +
  `EntryEditor.vue:967-1046` — keystrokes typed during an in-flight save are
  marked clean (`snapshot()` stringifies live refs post-await) and never
  persisted; `close()` then discards the crash draft. Snapshot from the
  payload values, or re-arm the debounce on the skip path.
- [ ] `backend/app/core/database.py:288-305` — `lifelogr.db.corrupt-*`
  quarantine copies are never pruned (boot snapshots rotate at 5; quarantine
  doesn't). A failing disk writes one full-DB-size file per boot attempt.
- [ ] `backend/app/core/jobs.py:254-272` + `routers/backup.py:281` — export
  temp handling is inconsistent: job exports go to `DATA_DIR/tmp` with no boot
  sweep after a crash, while `export_local_backup` stages a full DB+media
  archive in system `/tmp` (tmpfs risk). One policy + a boot sweep + a
  free-space check.
- [ ] No free-space checks on backup/restore staging
  (`scheduler_service.py:779-805`, `backup_service.py:190,493`,
  `routers/backup.py:415`) — only the hot-move checks headroom
  (`storage_service.py:100-106`).
- [ ] `backend/app/main.py:572-660` — `/health` has no data-dir
  writability/disk-space signal; a full or read-only volume keeps the
  Docker container "healthy" while every write 500s.
- [ ] `backend/app/services/ai_provider_service.py:93,111-112` — custom
  provider `base_url` accepts any string (contrast the scheme+loopback+consent
  checks on `ollama_base_url` in `routers/settings.py:165-178`); stored API
  keys are later sent to it as Bearer headers. At minimum validate scheme.
- [ ] `backend/app/services/media_service.py:758-768`,
  `note_media_service.py:259-265`, `video_service.py:126-133` — these three
  deletes unlink files *before* the DB commit, the opposite of the ordering
  `entry_service.soft_delete` documents and deliberately uses
  (`entry_service.py:317-320`).
- [ ] Config/environment (browser/Docker variant): `Dockerfile:10,15` ignores
  `uv.lock` (floating `uv:latest`, resolve-at-build deps); `docker-compose.yml`
  loads `backend/.env` wholesale, injecting dev `DATABASE_URL` (DB lands
  outside the mounted volume), dev `SECRET_KEY`, and a real OAuth secret into
  the container; `frontend/package-lock.json` root version is stale at 0.13.0.

## Low priority

- [ ] Shutdown guard can kill foreign listeners: `port_is_lifelogr`
  (`desktop/src-tauri/src/main.rs:147-164`) matches any 200 body containing
  "ok" before `fuser -k`; parse the actual `{"status": "ok"}` shape.
- [ ] `waitForBackend` (`frontend/src/api/client.ts:24-27`) discards the
  `/health` body — a corrupt-DB boot surfaces as generic "Backend failed to
  start" instead of "Database unavailable"; `/health` also `logger.error`s
  per poll (~30 duplicate lines per failed boot) (`main.py:593`), and its
  soft-check failures are unlogged (`main.py:604-614,659-662`).
- [ ] `note_media_service.py:110,177,180` — media written to final path
  without temp+rename (ENOSPC leaves orphaned truncated files); TTS and
  imports already do it correctly.
- [ ] `EntryEditor.vue:1329` (delete catch swallows 500s as "already gone"),
  `:1056-1061` (unhandled clipboard promise), `:1357` (AI tag-suggest button
  fails silently — a click, not a background load).
- [ ] Reminder catch-up double-fire window (~sub-second race,
  `scheduler_service.py:637-660/908-938`); notification-only impact.
- [ ] Stats cache not invalidated on media mutations despite the stated
  contract (`entry_service.py:104-108` vs `routers/media.py` — stale media
  counts up to 60 s).
- [ ] Bulk dedupe soft-deletes without the single-path media policy
  (`routers/entries.py:995-1009`) — restore-after-dedupe keeps attachments,
  restore-after-single-delete can't (resolution follows the blocker above).
- [ ] CI/testing: ESLint never runs in CI (ci.yml frontend job); Playwright
  has zero retries (`playwright.config.ts`) and CI hard-enumerates spec files;
  frontend stores largely untested (notably `stores/tts.ts`); OCR byte-path
  test skipped in CI (no tesseract installed); `SearchPalette.mount.test.ts:93`
  uses a real-timer sleep where fake timers are the established pattern; no
  frontend coverage measurement.
- [ ] `backend/.env.example` missing 12 operator fields (BIND_HOST/BIND_PORT,
  API_TOKEN, DATA_DIR, BACKUP_ALLOWED_ROOTS, …); `OCR_ENGINE` documented but
  nonexistent (`DEPLOYMENT.md:413`, `.env.example:47`); sidecar env table
  lists `DIARI_DATA_DIR` but the code sets `DATA_DIR` (`main.rs:613`);
  undocumented env-only knobs `BACKUP_CLOUD_RETENTION`
  (`backup_service.py:48`) and `LIFEOGRF_ENRICHMENT_CONCURRENCY`
  (`enrichment_service.py:43`); `BIND_HOST`/`BIND_PORT` inert under Docker's
  hardcoded CMD (documented, but silently ignored).
- [ ] Cloud-sync `_list_all_names` failures log at DEBUG only
  (`cloud_sync_service.py:757-762`) — provider auth failure reads as "0
  backups found" at INFO.

## Explicitly out of scope / accepted risk

- **`trash2review/`** — this pipeline's holding pen (9 tracked files from the
  2026-10-27 run plus the dead `schemas/sync.py` from this pass). Not dead
  weight; awaiting human review.
- **Incremental sync merge machinery has no router caller** —
  `SyncService.push/pull` in `cloud_sync_service.py` is dead-ish code (only
  the providers feed `backup_service`) since `/api/v1/sync` was parked in the
  prior pass. Kept intentionally; flagged so it isn't mistaken for live.
- **Rust shell has zero tests** — `main.rs` (720 lines) is a compile-gate-only
  thin shell (`cargo check` in CI). Accepted boundary.
- **CSP `style-src 'unsafe-inline'`** (`tauri.conf.json:25`) — standard Vue
  compromise; everything else strict.
- **Local `backend/.env`** holds a real-format Google OAuth client secret —
  untracked and gitignored (no history leak), but rotate it if that client is
  used beyond dev; installed-app client secrets are public anyway.
- **`RATE_LIMIT` knob** (`config.py:346`) — one reader, one value, never
  varied; demoting to a constant would break env override. Needs a maintainer
  decision either way (config knob vs module constant like
  `_DESTRUCTIVE_RATE_LIMIT`).
- **`services/` naming split** — 24 `*_service.py` class modules vs 6 bare
  pure-function modules, and two parallel export modules with no
  name-level boundary signal. Rename would be churn-heavy; documented here
  instead.
- **`MEDIA_IMPORT_ALLOWED_ROOTS`** stays env-only (deliberate; documented at
  `media_service.py:63-68`). Promoting it to a real Settings field would
  change behavior (`.env` deployments would start honoring it).
- **AI-settings field enumeration in three places** (`routers/settings.py:122,
  182`, `settings_service.py:33`) — deriving from `model_fields` was declined
  as a style trade-off, not an oversight.
- **Synchronous non-job `/restore`** (`routers/backup.py:249-254`) — UI uses
  the job variant; kept for compatibility, undocumented black hole for direct
  API callers.

## Verification note

Every finding above carries file:line references from independent audit
agents; none have been fixed by this pipeline (this pass's phases 1–3 were
behavior-preserving cleanup only). `.pipeline/blind-review.md` holds an
independent cold review reconciled against this document.
