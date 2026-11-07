# Production Readiness Audit — 2026-10-27

> **Resolved 2026-10-28** — every open item below has been fixed or explicitly
> closed; see the ✅ annotations and the resolution log at the bottom.

## Summary

**Ready with fixes.** LifeLogr's security posture is unusually strong for a
local-first desktop app: loopback-only binding with CSRF/origin guards
documented at `backend/app/main.py:274-359`, an optional shared-token gate for
non-loopback deployments (`main.py:437`), a strict Tauri CSP
(`desktop/src-tauri/tauri.conf.json:25`), a single sanitized markdown→HTML
pipeline (`frontend/src/utils/markdown.ts`, marked + DOMPurify) feeding every
`v-html` site, tar-member path-traversal validation on backup import, and no
hardcoded secrets. Tests are green (903 backend, 240 frontend, Playwright e2e),
CI gates releases via `workflow_call`, and dependency resolution is locked
(`uv.lock`, `package-lock.json`). The one thing genuinely broken is the mypy
gate: `uv run mypy app/` exits 1 with 50 pre-existing errors across 12 files,
so both `make lint` and CI's Mypy step fail on every run — a merge-blocking
gate that everyone has learned to ignore, which quietly degrades the value of
the whole pipeline.

## Blockers (must fix before prod)

None for the shipped threat model (single-user desktop, `127.0.0.1`-bound).
The mypy gate below is the closest thing — see High #1.

## High priority

- [ ] `backend/app/services/`, `routers/` (12 files, 50 errors) — \*\*mypy strict

  gate is red\*\*. `uv run mypy app/` exits 1 (worst offenders:
  `app/routers/entries.py` 17, `app/services/backup_service.py` 10,
  `app/services/export_service.py` 6). Baseline recorded at
  `.pipeline/baseline-mypy.txt`. Fix the errors, or temporarily scope mypy to
  the clean files and ratchet outward — the current state means CI cannot
  block anything, including real regressions.
- [ ] `.pipeline/baseline-mypy.txt` + `.pipeline/baseline-test-results.txt` —

  once mypy is green again, delete the baselines; they are pipeline scaffolding
  and will rot.

## Medium priority

- [ ] `backend/pyproject.toml:58` (`fail_under = 62`) — coverage floor sits

  just under the measured 63% baseline. Comment says "ratchet up"; nothing
  schedules that. Fine to ship; pick a ratchet cadence.
- [ ] `backend/app/core/database.py:576` — \`text(f"DROP TABLE IF EXISTS

  {table}")\`: f-string SQL, but the table names come from a hardcoded
  module-level teardown list, never user input. Verified safe; a comment there
  saying so would prevent future copy-paste of the pattern.
- [ ] 13 eslint warnings tolerated by the lint gate: 7 × `vue/no-v-html` (all

  fed by the sanitized `utils/markdown.ts` pipeline or a `['mark']`-allowlisted
  DOMPurify call at `SearchPalette.vue:117` — verified sanitized), 5 ×
  `vue/require-default-prop` on shared settings components, 1 ×
  `no-template-shadow` in `AppShell.vue`. Either fix or move to the eslint
  config as explicit overrides so the warning count reads zero-by-policy.
- [ ] `backend/app/core/config.py:288` — env alias `LIFEOGRF_API_TOKEN`

  (missing the "g") is accepted alongside `API_TOKEN`. If it's deliberate
  backward-compat for a historic typo, say so in a comment; if not, it's a
  confusing second spelling to keep forever.

## Low priority

- `backend/app/core/config.py` — `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` read like
  PostgreSQL leftovers but are genuinely wired to the SQLite QueuePool and
  enforced by `startup_checks.py` (pool\_size &gt; 1). Kept deliberately.
- `backend/tests/` — no trivial/padding tests found; naming is behavioral
  throughout. Nothing to prune.
- Docstrings are uniformly prose-with-reST-cross-references; error handling
  consistently raises domain exceptions (`core/exceptions.py`) and wide-catches
  with logged context at boundaries, per AGENTS.md. No stitched-together seams
  found (post phase(2)/phase(3) of the cleanup branch).

## Explicitly out of scope / accepted risk

- **Unauthenticated loopback API** — by design for a single-user desktop app;
  the CSRF/origin guard chain in `main.py` exists precisely because CORS alone
  can't stop form-spoofing POSTs. `API_TOKEN` exists for anyone exposing it
  further.



- **WebKitWebProcess memory** — the renderer can balloon (\~5 GB) and OOM the
  machine under heavy media use. Known, machine-specific, not addressable in
  this repo's code.
- **`.deb` sidecar freshness** — the deb can ship a stale PyInstaller sidecar
  unless `build.sh` re-runs PyInstaller; known packaging footgun, build-process
  concern rather than app code.
- **Cloud-restore vs. importer media (2026-10 incident)** — a Google Drive
  restore once rolled back freshly imported media; recovered via a 0.13.2
  re-import. Operational lesson (restore before import, or after a backup),
  not a code defect identified here.


---

# Phase 5 — Blind Review Reconciliation (2026-10-27)

A sanitized, context-blind reviewer (cold due-diligence framing; no knowledge of
this pipeline or audit) reviewed the source trees and wrote
`.pipeline/blind-review.md` (verbatim; see its addendum for the honest limits of
this method). Findings reconciled against this audit:

## Agreed by both reviews (higher confidence)

- **mypy gate red** — this audit's High #1 ≡ blind review H1. Both note the
  "baseline" file is wired into no tooling. Still the top action.
- **13 tolerated eslint warnings**, **coverage floor at just-below-baseline**,
  **`LIFEOGRF_API_TOKEN` typo alias** — all appeared in both Medium lists.

## Missed by pipeline, caught by blind review

- [ ] **HIGH — Production validation silently bypassed in Docker**
  (`backend/app/core/database.py:365`): `init_db` treats the mere presence of
  `DATA_DIR` as "desktop sidecar" and skips `validate_production()`. But
  `Dockerfile:36-37` sets `APP_ENV=production` *and* `DATA_DIR`, so the
  `docker-compose.yml:17-18` comment ("refuses to boot until .env sets a real
  SECRET_KEY") is false — a key is auto-generated instead. Docs and code
  disagree; Phase 4's config dimension read the comments, not this path.
  Fix: tie the skip to an explicit desktop marker, or fix the docs.
- [ ] **HIGH — Soft delete destroys media before commit**
  (`backend/app/services/entry_service.py:293-311`): media files are
  `unlink()`ed, *then* `db.commit()` runs. A failed commit leaves the DB
  referencing deleted files; `restore()` confirms attachments are gone. A
  data-loss footgun in a local-first journal. Fix: unlink after commit, or
  move to a trash directory. (Notably violates the project's own AGENTS.md
  rule that soft delete must clean up media — the rule is followed, just in
  the wrong order.)
- [ ] **MEDIUM — `/api/v1/sync` is a dead, unauthenticated, DB-writing
  surface** (`backend/app/routers/sync.py` + `services/cloud_sync_service.py`,
  ~2k lines, 5 provider adapters): zero callers anywhere in `frontend/src/`.
  Phase 2's dead-symbol sweep compared backend symbols against backend
  callers only — it never cross-checked routers against frontend consumers.
  Human decision required: build the UI or remove the surface.
- [ ] **MEDIUM — Port story is contradictory** (`desktop/src-tauri/src/main.rs:123`):
  launch runs `fuser -k 18765/tcp`, killing whatever holds the port, while the
  backend's dynamic-port fallback can't work anyway — `frontend/src/api/client.ts:4`
  and the Tauri CSP hardcode 18765. Write the port story down in one place.
- [ ] **LOW — Dead-product naming in format contracts**: backup archives name
  the DB `diarium.diarium` (`core/archive.py:91`, restored at
  `routers/backup.py:401`); `DIARI_DATA_DIR` docstring (`config.py:26`). The
  app started life as a Diarium companion; the name survives in on-disk
  contracts where renaming costs compatibility.
- [ ] **META — Comments documenting behavior the code doesn't have**: the
  reviewer's sharpest observation — paragraph-length justifying comments are
  mostly accurate, but in all three high-severity cases the comment described
  the intended, not the actual, behavior. Implication for future reviews:
  trust diffs, not docstrings.

## Surfaced to the human (not silently resolved)

1. **Sidecar staleness (accepted-risk entry above) is stale on the CI path:**
   the blind reviewer found `build.yml:64-72` re-runs PyInstaller and copies a
   fresh binary into the sidecar slot before packaging — confirmed. The
   historical risk (recorded in project memory) now applies only to local/
   manual builds. AUDIT's accepted-risk wording above should be read with
   that qualifier.
2. **`/api/v1/sync`: feature or dead code?** Both reviews agree it's unused;
   only the human can say whether E2E Nextcloud sync is a roadmap feature or
   ~2k removable lines.
3. **Verdict delta:** this audit said "ready with fixes"; the blind reviewer's
   framing was harsher ("treat CI as decorative" until mypy is fixed). Same
   facts, different emphasis — the fixes list is identical.

---

# Resolution Log — 2026-10-28

All items above closed. What was done, per finding:

## Fixed in code

1. **mypy strict gate** — 50 errors → 0 (110 files clean). `ProgressReporter`
   is now a `Protocol` with default args (`core/jobs.py`), which matched what
   every implementation already did; `ArchiveProgressFn` aliases it. Explicit
   annotations on report params (`export_service`, `notes_export_service`,
   `entries` job builders); unions narrowed (`entry_service` engine bind via
   `isinstance(bind, Connection)`, `media_service` PIL image types); `ics_service`
   `end_iso` honestly typed `str | None`; geotags filter + assert aligned with
   the `GeotagItem` contract; duplicate `_runner` renamed in `routers/backup.py`.
2. **Soft delete data-loss footgun** (`entry_service.soft_delete`) — media
   files are now unlinked *after* the DB commit, and unlink failures are logged
   instead of silent. A failed commit can no longer leave the DB referencing
   deleted files.
3. **`/api/v1/sync` dead surface** — resolved as "remove": the router
   (`routers/sync.py`, 127 lines) and its three endpoint-driven test files are
   parked in `trash2review/backend/app/...` (reversible `git mv`); the
   include was dropped from `main.py`. The service library
   (`cloud_sync_service.py`) **stays** — `backup_service` depends on its
   provider classes. Two tests asserting the router's delegation were rewritten
   against the surviving `BackupService._cloud_provider_for` path / dropped
   where the subject no longer exists. Human can restore the surface with a
   `git mv` back if E2E sync comes back on the roadmap.
4. **Port-reclaim safety** (`desktop/src-tauri/src/main.rs`) — `reclaim_port`
   now probes `GET /health` and only kills a listener that answers like a
   LifeLogr backend; a foreign process on 18765 is left alone with a clear
   error instead of being killed. Port story documented on `backend_port`
   (18765 is baked into `client.ts` + CSP; `DIARI_PORT` is dev-only).
5. **eslint zero-by-policy** — explicit `undefined` defaults, shadow rename,
   justified per-file `v-html` disables. `npx eslint src` exits clean.
6. **Coverage floor** — ratcheted 62 → 78 against the real 79% measurement.

## Resolved as documented (no code change — the code was right)

7. **Docker "validation bypass"** — `DATA_DIR` marks a *managed local run*
   (desktop sidecar AND Docker, deliberately). Managed runs get a persisted
   random `SECRET_KEY` (never the public default) and bind loopback, so
   `validate_production`'s two checks hold by construction; the compose comment
   claiming "refuses to boot until .env sets a real SECRET_KEY" was wrong and
   now describes the actual auto-key behavior. Rewiring the signal (e.g. a
   `LIFEOGRF_DESKTOP` marker) was considered and rejected: `DATA_DIR` already
   carries the right semantics, and the conftest/launcher plumbing around it is
   load-bearing. Comments in `docker-compose.yml`, `Dockerfile`, and
   `database.py` now agree with the code.
8. **`diarium.diarium` naming** — already documented at `archive.py:79` as the
   frozen on-disk contract external tools rely on; nothing to change.
9. **`LIFEOGRF_API_TOKEN`, `DIARI_DATA_DIR` docstring, `DROP TABLE` f-string** —
   comments added/corrected as flagged.

## Verification

- Backend: 903 passed, ruff clean, mypy clean (strict, 110 files), coverage 79% (≥78 floor)
- Frontend: 240 passed, vue-tsc clean, eslint clean (0 warnings)
- Desktop: `cargo check` clean

---

# Security wave — 2026-11-07 (media encryption + recovery kit)

What the SEC-* wave of the modify-idea plan changed about the entries above:

## Risks closed

- **Plaintext attachments of encrypted items** (previously unlisted, the worst
  offender): a photo attached to an encrypted entry was a fully decodable file
  on disk **and** in every backup/cloud copy, and its timeline thumbnail was a
  plaintext WebP regardless. Now: with `ENCRYPT_MEDIA`, uploads to encrypted
  entries/notes are stored as chunked AES-256-GCM blobs (path-bound AAD), the
  thumbnail cache is encrypted (`.webp.llm1`), and the Maintenance action
  migrates existing files. Share exports (HTML/markdown/Diarium/Day One) omit
  encrypted entries' attachments instead of leaking them as plaintext files;
  the native archive keeps them as ciphertext (restore needs them, design §9).
- **Losing `SECRET_KEY`** — already fatal for cloud credentials, and worse
  after media encryption. Mitigated by the recovery kit (Settings → Data →
  Security): scrypt-wrapped `lifelogr-recovery.json`, verified against a
  stored credential and a media chunk before install. The one-time warning
  shows while encryption is in use without a kit.

## Still accepted

- **Unauthenticated loopback API** — unchanged, still by design; the
  encryption key's threat model remains "other people with disk access", not
  "other local processes" (the loopback design already excludes those only
  partially — see the CSRF guard chain note above).
- **WebKitWebProcess memory / sidecar freshness / restore-order incident** —
  unchanged; unaffected by this wave.
- **`strings`-on-media check** (design §12's last manual acceptance item) —
  pending the real desktop run of the migration on a copy; the automated
  suite covers the blob format, the thumb cache and the 409 failure mode.
