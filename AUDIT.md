# Production Readiness Audit — 2026-10-27

## Summary

**Ready with fixes.** LifeLogr's security posture is unusually strong for a
local-first desktop app: loopback-only binding with CSRF/origin guards
documented at `backend/app/main.py:274-359`, an optional shared-token gate for
non-loopback deployments (`main.py:437`), a strict Tauri CSP
(`desktop/src-tauri/tauri.conf.json:25`), a single sanitized markdown→HTML
pipeline (`frontend/src/utils/markdown.ts`, marked + DOMPurify) feeding every
`v-html` site, tar-member path-traversal validation on backup import, and no
hardcoded secrets. Tests are green (932 backend, 240 frontend, Playwright e2e),
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

- [ ] `backend/app/services/`, `routers/` (12 files, 50 errors) — **mypy strict
  gate is red**. `uv run mypy app/` exits 1 (worst offenders:
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
- [ ] `backend/app/core/database.py:576` — `text(f"DROP TABLE IF EXISTS
  {table}")`: f-string SQL, but the table names come from a hardcoded
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
  enforced by `startup_checks.py` (pool_size > 1). Kept deliberately.
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
- **WebKitWebProcess memory** — the renderer can balloon (~5 GB) and OOM the
  machine under heavy media use. Known, machine-specific, not addressable in
  this repo's code.
- **`.deb` sidecar freshness** — the deb can ship a stale PyInstaller sidecar
  unless `build.sh` re-runs PyInstaller; known packaging footgun, build-process
  concern rather than app code.
- **Cloud-restore vs. importer media (2026-10 incident)** — a Google Drive
  restore once rolled back freshly imported media; recovered via a 0.13.2
  re-import. Operational lesson (restore before import, or after a backup),
  not a code defect identified here.
