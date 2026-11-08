# Refactor Plan — 2026-11-08 (second pipeline pass, Phase 2 dry run)

No edits made yet. Units are ordered; each lands as its own `phase(2):` commit
with tests re-run. Only behavior-preserving changes are proposed; anything
behavior-risky is flagged at the bottom.

## Unit A — fix the red baseline (frontend tests) · HIGH
`frontend/src/components/entry/EntryEditor.mount.test.ts:19`,
`EntryEditor.title.test.ts:21`
Both mock `entriesApi.get` with `{}` — no `tags` — so `EntryEditor.vue:747`
`entry.tags.map(...)` throws as an unhandled rejection and vitest exits
non-zero (this is the baseline red). `EntryResponse.tags` is required in both
the frontend types (`types/index.ts:45`) and backend schemas
(`schemas/entry.py:112,142,170`), so production is fine; the mocks are wrong.
**Change:** give both mocks a minimal well-formed entry; also mock
`../../api/tts` in both files (the ECONNREFUSED 127.0.0.1:3000 noise comes from
unmocked `tts.prewarmEntry`, swallowed by the store but fatal to output
cleanliness). Do NOT add optional chaining at :747 — it would mask a real
contract violation. Result: `make fe-test` goes green.

## Unit B — dead type exports · HIGH
`frontend/src/types/index.ts`: 16 exported interfaces with zero references
repo-wide (verified per-symbol across src/tests/e2e): PaginatedParams,
GrammarCheckResponse, SpellCheckResponse, ContinueWritingResponse,
ChangeToneResponse, AnalyzeTextResponse, DefineTextResponse,
VoiceChangeResponse, RewriteForClarityResponse, VideoNoteResponse,
OverviewResponse, WritingHabitResponse, WordCountResponse, TagStatsResponse,
HeatmapDayResponse, HeatmapResponse, MediaStatsResponse.
**Change:** delete them. Keep TagBrief/EntryEventBrief (used intra-file by
EntryResponse).

## Unit C — dead custom CSS · MEDIUM-HIGH
`frontend/src/styles/main.css`: `.animate-in`, `.fade-in`,
`.slide-in-from-bottom-2`, `@keyframes fadeIn`, `@keyframes slideInFromBottom`,
`.transition-smooth`, `.sbtn-outline`, `.sbtn-accent-soft`, `.sbtn-danger-soft`
— zero substring hits across src+tests (substring search also covers composed
class names). **Change:** delete the self-contained blocks.

## Unit D — shared test-mock factories · MEDIUM
Six test files re-declare near-identical `vi.mock` API blocks (~70 lines each):
EntryEditor.mount, EntryEditor.title, NoteEditor, MediaTimelineView.mount,
TimelineView.mount, ContextDrawerPanel. **Change:** one shared module with
pure factory functions, called from each file's hoisted `vi.mock`. This kills
the drift that caused Unit A. Skipped if Unit A review shows the mocks diverge
more than reported.

## Unit E — one spool-upload helper (backend) · HIGH
Three ~25-line copies of the chunked temp-file upload loop:
`services/media_service.py:166-190`, `routers/backup.py:310-338`,
`routers/entries.py:1251-1281` (the cap check has already drifted cosmetically
between copies). **Change:** one helper parameterized by the overflow
exception (`MediaSizeError`→400 stays; `HTTPException`→413 stays); plus the
incidental `ensure_within_media_cap(size)` helper collapsing the six two-line
cap gates (media_service:334, note_media_service:72,141, video_service:44,90,
media_service:185).

## Unit F — atomic-write dedup (backend) · HIGH (identical pair) / MEDIUM (rest)
`core/restore.py:162-170` `_atomic_write` and `services/storage_service.py:40-48`
`_atomic_copy` are byte-for-byte identical; storage_service already imports
from restore. **Change:** delete `_atomic_copy`, use restore's function.
The five other variants (config.py:97,234; weather_service.py:184; tts.py:206;
media_service.py:738) differ legitimately (unique tmp names, umask) — leave,
note in AUDIT.md.

## Unit G — get-or-raise consolidation (backend) · HIGH (mechanical subset)
11 re-derivations of fetch-by-id-or-raise. **Change:** add
`get_entry_or_raise(db, id, *, include_deleted=False)` on EntryService (and a
note twin); migrate the mechanical copies (media_service._require_entry,
video_service, encryption_service, recording_service, tts.py, note_media_service).
The `is_deleted` difference becomes an explicit parameter — several call sites
require the deleted row, so blind unification is off the table. media_service's
copy lacks the filter; verify intent (deleted entries' attachments stay
servable) via existing tests before delegating; if a test disagrees, that
call site keeps its filter via the parameter.

## Unit H — phantom setting + dead getattr (backend) · HIGH
`services/media_service.py:66-69,108-110`: `MEDIA_IMPORT_ALLOWED_ROOTS` is not
a Settings field, so the settings half of the `or` never fires; read
`os.environ` directly (behavior-identical). `core/paths.py:44`: field exists,
drop the getattr default. **NOT doing:** promoting MEDIA_IMPORT_ALLOWED_ROOTS
to a real Settings field — that changes behavior (`.env` would start being
honored); flagged for AUDIT.md instead.

## Unit I — hoist redundant local imports (backend) · HIGH (trivial)
`routers/settings.py:165-167,372-374`: local `HTTPException` (already imported
at top, line 9) and `urlparse` (stdlib) — move to top. The other local imports
in that file are deliberate lazy loads; untouched.

## Unit J — `_check_signature` promotion (backend) · MEDIUM-HIGH
`routers/entries.py:1356-1362` calls private `MediaService._check_signature`
inside a try that also wraps the import, catching everything as "blocked".
**Change:** promote to a module-level function in `media_service` (next to
`_BLOCKED_SIGNATURES`), import at top, catch `MediaSizeError` specifically.

## Flagged — leave alone (behavior or intent)
- AI-settings field enumeration in 3 places (settings.py:122,182;
  settings_service.py:33) — deriving from `model_fields` is mechanical but the
  explicit dict is self-documenting; human's call.
- Static-only `EnrichmentService`/`WeatherService` classes — namespaces, but
  readable call sites and deliberate mirroring; leave.
- `void loadEntry()` fire-and-forget; silent background catches — match
  existing convention; hardening is out of scope.
