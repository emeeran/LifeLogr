# Phase 3 — Style & Authorship Pass (DRY-RUN PLAN)

Generated for branch `debloat`. **No changes applied yet.** Plan only; `--apply`
runs the chosen items.

Method: detect configured formatters; `ruff format --check` (backend) and
`prettier --check` (frontend); emoji/exclamation scan over logs/raises/details;
naming & structure review against the oldest hand-written files.

## Headline

The codebase is **already stylistically cohesive where a standard exists**.
Backend has ruff configured and 99/146 files conform. Frontend has **no
formatter config** and no consistent style to enforce — so most of Phase 3's
"one formatting standard" work is either a safe finish-what's-there (backend)
or a deliberate convention decision the maintainer should make (frontend),
not a unilateral imposition.

---

## TIER 1 — Recommended apply (matches existing convention, behavior-free)

### Backend: finish the established ruff standard
- `ruff format app/ tests/` — 47/146 files drift from the configured ruff
  (line-length 100) standard that the other 99 already follow. Reformatting
  them *matches the majority*, doesn't impose anything new. Pure whitespace /
  line-wrap / quote-normalization; zero behavior change.
- `ruff check` already passes (import order + lint rules clean), so import
  hygiene and docstring-related lint are fine — no separate pass needed.

## TIER 2 — Decision required (flagged, NOT auto-applied)

### Frontend formatter: none configured
- No `.prettierrc`, no `prettier` key in package.json. `prettier --check`
  flags **115 files**, and they don't satisfy prettier even under
  `{semi:false, singleQuote:true}` — i.e. the frontend was hand-formatted
  with no single standard (mixed quote/semi/wrap choices).
- **Per "match conventions, don't impose new ones," I will NOT run prettier
  unilaterally.** Adopting a formatter is a project-wide convention choice.
- Recommended (separate decision): add `.prettierrc` (`semi: false,
  singleQuote: true` to match the dominant hand-style) + a `format` npm
  script, then `prettier --write`. Flagged in `AUDIT.md` under config/CI.

## TIER 3 — Reviewed, no change (documented)

### AI voice — clean
- Backend `logger.*`, `raise`, `HTTPException(detail=…)` contain **no emoji
  and no exclamation-heavy phrasing**. Good.
- Emoji exists only in OAuth callback HTML pages (`routers/{onedrive,box,
  google_drive,dropbox}.py`): `📦 🎉 ❌ ✅` on "Box Connected!" / "Auth failed"
  pages. This is **intentional product UX** (branded success/fail screens),
  not log/error voice. Leaving it matches the existing human-written tone.
  Stripping it would change product behavior, which is out of Phase 3 scope.

### Naming & structure — leave as-is
- `EmailAccountService` / `EntryService` / `AnalyticsService` etc. use a
  `*Service` suffix. This is the **established pattern** across the whole
  backend; renaming to "plain functions" would be massive churn against the
  grain of the codebase. The pipeline says match conventions — keep `Service`.
- The routers / services / models / schemas layering is justified for a
  multi-feature FastAPI app (this isn't a 300-line CLI). Not enterprise
  over-engineering. Keep.
- No `Manager`/`Handler`/`Helper`/`Util` dumping-ground suffixes found.

### Error-handling philosophy
- One philosophy is already in place: services raise `NotFoundError`/
  `ConflictError`/`ValidationError` (mapped to HTTP in exceptions.py); stores
  use try/catch→error ref. Consistent. (The *narrowing* of over-broad catches
  is a Phase 4 AUDIT item, Phase 2 Tier C, not a style issue.)

### Tests
- Spot-checked: the 294-test suite is substantive (real CRUD/edge/failure
  paths in test_email/test_spam/test_notes/test_contacts), not padded with
  trivial getter-roundtrip tests. No padding-tests removed.

---

## Recommended `--apply` scope

**Tier 1 only: `ruff format app/ tests/` (backend).** ~47 files reformatted,
zero behavior change, finishes the existing standard. Re-run `pytest` after
(formatting must not break tests). Tier 2 (frontend formatter) is a maintainer
decision; Tier 3 needs no action.
