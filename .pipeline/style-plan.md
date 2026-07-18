# Phase 3 — Style & Authorship Pass (DRY-RUN PLAN)

Generated for branch `cleanup/pipeline-2026-07-18`, 2026-07-18. **No changes applied yet.**
Plan only; `--apply` runs the chosen items.

Method: detect configured formatters/linters; run the existing ones (`ruff`); emoji /
exclamation / suffix scan over logs, raises, toast/error strings; naming & structure review
against the codebase's dominant patterns.

## Headline

The codebase is **already stylistically cohesive**. CI gates `ruff` (line-length 100, py311) +
`mypy --strict` on the backend and `vue-tsc` on the frontend, and the 2026-07-12 humanize
pass already erased most seams. Detection this run confirms it:

- **No `Manager`/`Handler`/`Helper`/`Util` scaffolding** — 0 such classes. 24 `*Service`
  classes, which is the deliberate service-layer convention.
- **Vue SFCs uniform** — all 77 `.vue` files use `<script setup>`; no Options-API stragglers.
- **Types uniform** — `types/index.ts` is 106 `export interface` vs 1 `export type` (a
  dominant, consistent preference).
- **No AI voice** — no exclamation-heavy toast/error strings; no emoji in `logger.*` calls
  (the only non-plain glyph is a `→` arrow in 2 `config.py` migration logs).
- **Error-handling philosophy is layered and consistent** — services raise domain
  exceptions (`ConflictError` / `NotFoundError` from `app.core.exceptions`); routers
  translate to `HTTPException`. 21/33 service files `raise`; the rest are pure CRUD that
  legitimately return values.
- **Docstrings are short module-level one-liners** (`"""Business logic for X."""`) — there's
  no heavy Google/NumPy/reST convention to drift against, so docstring-format consistency
  is a non-issue.

What remains is a short list — and most of it overlaps Phase 2 (the same `errMsg`/`catch`
items are both a dedup win and a consistency win). Reported as-is, not padded.

---

## Actionable on `--apply` (all LOW risk)

| # | location | what | rationale |
|---|----------|------|-----------|
| S1 | `backend/app/core/config.py:100,114` | replace the `→` arrow with `->` in the two migration log lines | only non-plain glyphs in the logging surface; rest of the codebase logs plain ASCII. Trivial consistency. |
| S2 | *(same as Phase 2 F2)* | extract `errMsg(e)` util | consistency dimension of the 18× duplication — every component handling errors the same way. |
| S3 | *(same as Phase 2 F6)* | 4× `catch (e: any)` → `catch (e: unknown)` | consistency: the rest of the frontend standardised on `unknown`. |

> S2/S3 are listed here for the consistency record but are **executed under Phase 2** (F2/F6)
> on `--apply` — not done twice.

---

## Deferred / recommendation (needs your decision — not auto-applied)

| # | item | note |
|---|------|------|
| D1 | **Frontend has no formatter/linter.** Backend is `ruff`-gated; frontend relies only on `vue-tsc --noEmit`. | Over time this is where authorship drift will creep in (the `catch (e:any)` stragglers and `errMsg` re-derivation are early symptoms). Recommend adding `prettier` + `eslint` with a minimal config matching the existing style, gated in CI alongside `vue-tsc`. **Per the pipeline rule, a formatter is NOT introduced without asking** — flagged here for your call. |
| D2 | The `→` in `config.py` is arguably fine (descriptive). If you prefer the arrow for readability, skip S1. |

---

## Explicitly NOT touched (consistent, leave alone)

- `*Service` class naming — intentional service-layer convention, 24 files.
- Module-level one-liner docstrings — sparse by design; no format war to wage.
- `interface` vs `type` — 106:1 is a clear, consistent choice.
- Options-API / Composition-API mix — there is no mix (100% `<script setup>`).

## After --apply

Re-run `uv run ruff check .` (S1) and `npm run build` (S2/S3 via Phase 2). No behavior
change expected from any item.
