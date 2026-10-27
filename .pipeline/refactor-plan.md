# Phase 2 Refactor Plan — dry run (2026-10-27)

Method: dead-symbol sweep across backend (all `def`s, Settings fields) and
frontend (all `export`s), cross-referenced against full-source grep excluding
each symbol's own file. Route handlers and decorator-registered functions were
excluded as false positives. Broad `except Exception` blocks were reviewed but
left alone: wide-catch + `logger.warning(..., exc_info=True)` is the codebase's
existing error philosophy (AGENTS.md codifies it), and boot-safety code in
`core/database.py` legitimately catches wide.

## Proposed removals (no behavior change — all symbols are unreachable)

| # | location | what | why | lines saved |
|---|----------|------|-----|-------------|
| 1 | `backend/app/core/config.py:215` | `_is_loopback()` | Explicit "backwards-compatible alias" for `is_loopback_host`; zero callers anywhere in repo history-relevant source. Backwards compat with nothing. | 4 |
| 2 | `backend/app/services/ollama_service.py:74` | `entry_context_from()` | Dead in production: `routers/ai.py:_service_entry_context()` (ai.py:69) does the equivalent payload→EntryContext conversion for the actual request schema. Only callers are its own unit tests. This is the "same 10 lines re-derived in 2 places" pattern — the fix is deleting the unused copy, not extracting a third abstraction. | 17 + test |
| 3 | `backend/tests/unit/test_ai_system_prompt.py:133` | `TestEntryContext.test_entry_context_from_payload` + `entry_context_from` import | Tests exclusively for #2; die with it. `TestEntryContext`'s other case (context formatting) stays. | ~8 |
| 4 | `frontend/src/composables/useFormat.ts:5` | `formatEntryDate()` | Defined, never imported, never called anywhere in `frontend/src` (including tests). Superseded by `formatDDMMYYYY`, which every consumer actually imports. | ~16 |
| 5 | `backend/app/core/config.py:351` | `OCR_ENGINE` setting | Never read anywhere; OCR is hardwired to Tesseract (project spec has exactly one OCR engine). Dead config knob. | 1 |

Total: ~46 lines, 5 symbols, 4 files.

## Considered and left alone (flagged, not touched)

- **`routers/entries.py` (1754 lines)** — large, but it's cohesive route-handler
  code; splitting it would churn imports across tests for zero behavior gain.
  Flag for AUDIT.md as a readability note, not a refactor.
- **`EntryEditor.vue` (1998) vs `NoteEditor.vue` (1658)** — apparent duplication,
  but the most recent feature commit was literally "editor unification"; the
  remaining overlap is likely deliberate. Do not re-litigate.
- **Wide `except Exception` blocks (~60)** — consistent with project convention
  (log-with-context). The handful of bare `except OSError: pass` / best-effort
  parse passes are narrow-typed and idiomatic. Error-handling consistency gets
  a verdict in Phase 4 instead of speculative edits here.
- **`OllamaService()` instantiated per request** in each ai.py handler — boring
  and stateless; a module-level singleton would be an abstraction, not a
  simplification.
- **Settings knobs like `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`** — commented as
  production-PostgreSQL leftovers and arguably dead in a SQLite-only app, but
  they ARE referenced in code, so removal changes the config surface. Flag in
  AUDIT.md (Phase 4, "config" dimension) rather than decide here.
