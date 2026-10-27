# Blind Review — LifeLogr (2026-10-27)

Reviewer: independent due-diligence pass before on-call handover.
Scope: `backend/app/`, `frontend/src/`, `desktop/src-tauri/`, build/lint/CI configs.
No prior audit notes were consulted before writing this.

## What I ran

| Check | Result |
|---|---|
| `cd backend && uv run pytest tests/ -q` | **932 passed** (50.6s) |
| `npm test --prefix frontend` (vitest) | **240 passed** (41 files) |
| `make lint` (ruff + mypy) | ruff clean; **mypy FAILS: 50 errors in 12 files** (`strict = true`) |
| `make fe-lint` | 13 eslint warnings (0 errors) |
| `make fe-typecheck` (vue-tsc) | clean |

Working tree was clean (only untracked `.pipeline/` scaffolding) at review time.

---

## Verdict

Genuinely strong codebase for its threat model — the security middleware stack
is thoughtful and *tested*, backup/restore has real traversal guards and
WAL handling, and the test suite is broad. But the build gate is broken
(mypy red on every run, so CI is a rubber stamp), two "documented" production
safety controls silently don't fire, and there is a sizeable dead subsystem
(`/api/v1/sync`) with unauthenticated mutating endpoints that no shipped UI
code calls. The code is unmistakably AI-generated at scale: nearly every
function carries a paragraph of design-justification comments. That is
readable, but it means comments document *intent*, not verified behavior —
and in the three cases below, intent and behavior have already diverged.

---

## High

### H1. The mypy gate is red; CI cannot block anything
- `backend/pyproject.toml:66` — `strict = true`.
- `make lint` → 50 errors in 12 files. Worst: `app/routers/entries.py` (17),
  `app/services/backup_service.py` (6+), `app/services/scheduler_service.py`,
  `app/routers/backup.py` (incl. `no-redef` of `_runner` at
  `routers/backup.py:184`).
- `.github/workflows/ci.yml` ("Mypy" step: `uv run mypy app/`) therefore fails
  on every push. Commit b95920a ("add mypy baseline (50 pre-existing errors)")
  recorded the errors in `.pipeline/baseline-mypy.txt` but wired the baseline
  into **no tooling** — it is a text file, not a gate. Consequence: everyone
  learns CI is always red, and it will not catch real regressions either.
  Same for the Makefile's own claim that `make check` "mirrors ci.yml" —
  it does, in the sense that both fail.

### H2. Production validation is silently bypassed in the documented Docker deployment
- `backend/app/core/database.py:365-367`:
  `is_desktop_sidecar = bool(os.environ.get("DATA_DIR"))` — if DATA_DIR is set,
  `settings.validate_production()` is skipped entirely.
- `Dockerfile` sets `ENV APP_ENV=production` **and** `ENV DATA_DIR=/app/backend/data`.
  So in the shipped Docker image the SECRET_KEY-must-be-set check and the
  refuse-non-loopback-bind check **never run**; instead
  `config.py:_resolve_secret_key` (gated on `_is_managed_run()`, which is true
  whenever DATA_DIR is set) quietly auto-generates `DATA_DIR/.secret_key`.
- `docker-compose.yml` comment explicitly claims: *"APP_ENV=production makes
  the app refuse to boot until .env sets a real SECRET_KEY … by design"* —
  that is false for this compose file. The behavior is arguably acceptable
  (random persisted key, host port pinned to 127.0.0.1), but the desktop
  sidecar heuristic (`bool(DATA_DIR)`) cannot distinguish a Tauri sidecar from
  a container, and the documentation contradicts the code. One of them is wrong.

### H3. "Soft" delete permanently destroys media files, before commit
- `backend/app/services/entry_service.py:293-311` (`soft_delete`): media files
  are `unlink()`ed from disk **and** their DB rows deleted, then `commit()`.
  If the commit fails (DB locked, crash, constraint), the files are already
  gone while the DB still references them — the unlink is not transactional.
- `restore()` (`entry_service.py:322-327`) documents that media deleted this
  way is unrecoverable. For a journaling app whose selling point is
  local-first data safety, a user-reversible "trash" action destroying
  attachments irrevocably (and before durability is guaranteed) is a data-loss
  footgun. At minimum: unlink only after a successful commit, or move files to
  a trash directory and purge on retention.

---

## Medium

### M1. Desktop launcher kills whatever holds port 18765
- `desktop/src-tauri/src/main.rs:123-155` (`reclaim_port`): runs
  `fuser -k 18765/tcp` unconditionally at startup if the port is busy. The
  comment's reasoning ("Single-instance is enforced, so anything on our port
  is stale") only covers *other LifeLogr instances* — a foreign service the
  user deliberately runs on 18765 gets SIGKILLed by launching the journal app.
- The whole dynamic-port story is inconsistent: backend comments
  (`main.py:407-409`, `config.py:277-280`) say launchers "pick the real port at
  start (18765, falling back to 8000-8019)", but the Tauri frontend hardcodes
  `http://127.0.0.1:18765` (`frontend/src/api/client.ts:4`) and the Tauri CSP
  pins 18765 (`tauri.conf.json:25`). Desktop cannot actually fall back — the
  fallback must be web-deb-only, but nothing says so in one place.

### M2. `/api/v1/sync` subsystem is dead surface from the UI
- `backend/app/routers/sync.py` (enqueue/pending/status/flush/cloud push/pull)
  plus `app/services/cloud_sync_service.py` (1,637 lines, five provider
  adapters, E2E passphrase encryption, resumable uploads) have **zero callers
  in `frontend/src/`** — no `fetch`/`request` path references `/sync`. The
  shipped backup UI uses `/api/v1/backup/*` instead. That is a large,
  unauthenticated, DB-writing API surface maintained for no user-visible
  feature. Delete it or ship it.

### M3. Legacy "Diarium" naming is baked into the backup format contract
- `backend/app/core/archive.py:91,98-100`: the LifeLogr database is written
  into every backup archive under the arcname **`diarium.diarium`** ("the
  on-disk name external tools expect").
- `backend/app/routers/backup.py:401-404` restores from `diarium.diarium`,
  with a `dev.db` fallback from an even older era.
- `backend/app/core/config.py:26` docstring still references `DIARI_DATA_DIR`.
- `export_service.py:514+` legitimately writes Diarium-compatible exports
  (that's a feature), but the app's *own* backup format using a dead product's
  doubled name is confusing for on-call and for users inspecting archives. The
  member name is a compatibility contract now — changing it needs a migration
  and accepting both names on read (the `dev.db` fallback shows this pattern
  already exists, once).

### M4. Env var alias `LIFEOGRF_API_TOKEN` (typo, missing "g")
- `backend/app/core/config.py:287-289` accepts `API_TOKEN` or `LIFEOGRF_API_TOKEN`.
  If deliberate, it's undocumented why; it reads as a typo enshrined in an alias.

### M5. Generic rate limiter has no direct tests and is desktop-noop by design
- `main.py:233-270`: the limiter is disabled unless `APP_ENV=production`
  (`main.py:238`), i.e. off for every desktop user and for the whole test
  suite (`APP_ENV=test`). Only the *destructive*-endpoint throttle is tested
  (`tests/unit/test_reset_guard.py`). The 429 path, the 10k-key sweep, and the
  media/thumb exemptions are exercised by nothing. Fine for the desktop threat
  model; wrong to discover during a server incident.

### M6. Coverage floor ratcheted to exactly-below-baseline with no plan
- `backend/pyproject.toml:58` — `fail_under = 62` against a measured ~63%.
  Comment says "ratchet up as coverage improves"; nothing schedules that, and
  with CI already red (H1) the floor is academic today. 932 backend tests but
  coverage concentrated in backup/importers/scheduler; routers like
  `routers/entries.py` (1,754 lines) are the light zone.

### M7. eslint warnings normalized rather than fixed
- 13 warnings incl. `vue/no-v-html` on `AboutTab.vue:334` (changelog — fed by
  the sanitized `utils/markdown.ts` DOMPurify pipeline, so OK in substance)
  and 5 × `vue/require-default-prop`. Either fix or encode as explicit config
  overrides so a *new* v-html site doesn't hide in the noise.

---

## Low

- **L1.** `main.py` is becoming a framework: 4 middlewares + health endpoint +
  SPA catch-all + exception table + Ollama probe cache in one file (~723
  lines). The guards are each individually good and tested; the file is where
  future regressions will live.
- **L2.** `scripts/build.sh` — `windows`/`mac` targets run the exact same
  Linux path (PyInstaller + `rustc -vV` host triple) and `android|ios` prints
  "Unknown target" despite being listed in usage. Dead branches.
- **L3.** `.pipeline/` and `trash2review/` are tracked in git — pipeline
  scaffolding and a quarantine dir don't belong on main.
- **L4.** Tauri CSP (`tauri.conf.json:25`) allows `style-src 'unsafe-inline'`
  and pins `http://127.0.0.1:18765` (see M1). Acceptable, but the port pin is
  a second copy of the same magic number the frontend also hardcodes.
- **L5.** `docker-compose.yml` healthcheck duplicates the Dockerfile one; and
  both hardcode the port that `config.py` documents as launcher-dynamic.
- **L6.** Observability is log-only (no metrics/trace), but structured enough
  (request IDs, per-subsystem `/health` checks with boot-time integrity
  results). Adequate for desktop; anyone running the Docker/server form factor
  will want log shipping + the `/health` mapped to their LB.
- **L7.** `dev.db` (208 KB) sits untracked in `backend/` — harmless, but it is
  the "even older era" filename that `backup.py:404` still honors.
- **L8.** Version parity is enforced in 4 places via `scripts/check_version.py`
  in CI — good — but `config.py:269` says "keep in sync with pyproject.toml"
  by hand-comment; the `make bump` path is the only reliable one.

---

## Things that are better than expected (for the record)

- CSRF/origin guard + separate destructive-endpoint guard + Host
  (DNS-rebinding) guard + optional bearer token (`main.py:273-446`) — each has
  written rationale and the destructive one has real tests
  (`tests/unit/test_reset_guard.py`).
- Backup import: streamed to disk with a 2 GiB cap, PEP 706 `filter="data"`
  extraction, per-member `..` segment check (`core/archive.py:27-53`), atomic
  restore with WAL sidecar handling (`core/restore.py`).
- Boot-time DB snapshot/rotate/quarantine-restore cycle (`core/database.py:198-348`)
  with integrity gating — unusually defensive for a local app, in a good way.
- FTS queries are parameterized and sanitized (`core/fts.sanitize_fts_query`,
  `search_service.py:125-258`); no SQL injection found; the two f-string DDL
  uses (`DROP TABLE IF EXISTS`) iterate hardcoded lists.
- Web-clip SSRF guard re-validates every redirect hop (`web_clip_service.py:64-84`);
  Ollama base URL change requires explicit `confirm_remote` for non-loopback
  (`routers/settings.py:152-169`).
- Per-item scrypt KDF with versioned salt format, embeddings deleted on
  encrypt so plaintext vectors can't outlive the ciphertext
  (`encryption_service.py`).
- OAuth: PKCE + single-use per-provider state stores (`core/oauth_state.py`).
- CI re-runs PyInstaller before packaging the sidecar (build.yml:66-72), so the
  historical "deb ships stale sidecar" failure mode is covered on the CI path.
- Frontend API client is clean: typed `ApiError`, timeouts everywhere, backend
  readiness wait in Tauri mode.

## Suggested handover order

1. Fix or scope the mypy gate (H1) — until then, treat CI as decorative.
2. Reconcile H2: either make Docker run `validate_production` or fix the
   compose/docs to say the key is auto-generated and validation skipped.
3. Re-order soft-delete media cleanup (H3) — unlink after commit or trash dir.
4. Decide `/api/v1/sync`: ship UI or delete ~2k lines (M2).
5. Write down the port story (18765 vs 8000-8019) in one place (M1).

---

## Addendum (appended by the reconciling session — not part of the review)

**What this pass is and isn't:** this reviewer ran on the same underlying model
as the work it reviewed. The sanitized dispatch removes self-grading and framing
bias, which are real, but not blind spots the model itself carries regardless of
context. For a genuinely independent signal, paste a sample of the finished code
into a fresh terminal / different reviewer.

**Residual exposure:** the working tree contained meta-directories
(`.pipeline/`, `trash2review/`, a root `AUDIT.md`) and branch history with
`phase(N)` commits while this review ran. The reviewer was scoped to the source
trees and reports no prior audit notes were consulted, but tree-level exposure
cannot be fully excluded from a cold review performed in-place.

**Verification of the top findings by the reconciling session:** all three
high-severity claims were independently confirmed in code (soft-delete unlink
before commit at `entry_service.py:293-311`; `DATA_DIR` guard bypass vs
`Dockerfile:36-37` + `docker-compose.yml:17-18` comments; zero frontend
callers for `/api/v1/sync`).
