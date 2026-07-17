# Phase 2 — Debloat & Refactor (DRY-RUN PLAN)

Generated for branch `debloat`. **No code has been changed.** This is the
human-review plan; `--apply` executes a chosen tier unit-by-unit, re-running
tests after each.

Source: 4 parallel read-only subagent scans (backend services/models, backend
routers/core/schemas, frontend stores/api/composables, frontend components),
~80 raw findings, de-duplicated and with subagent false-positives removed
(e.g. `SyncProvider` is *not* single-impl — 6 providers; entry/note
`_apply_filters` are *not* duplicates — different fields/strategies; the
recordings.py empty-FormData is a load-bearing WebKit2GTK workaround).

Guiding constraint applied throughout: **boring over clever; remove code
rather than add abstraction.** Anything that changes observable behavior is
kicked to Tier C (deferred to the Phase 4 audit), not applied here.

---

## TIER A — Dead-code removal (pure deletions, behavior-change-risk: no)

Recommended for `--apply`. Each is a deletion of something verified unreferenced.

### Backend
- `backend/app/schemas/ai.py` — delete unused classes: `SentimentData`,
  `EntryAnalysisResponse`, `SimilarEntry`, `SimilarEntriesResponse`,
  `DigestResponse` (router imports none).
- `backend/app/schemas/search.py:41` — delete `SearchFilter` (search router
  uses individual `Query` params).
- `backend/app/schemas/media.py:8` — delete `MediaCreate` (upload uses `Form`).
- `backend/app/schemas/encryption.py:40` — delete `EntryDecryptedResponse`.
- `backend/app/routers/entries.py:811` — drop redundant inner `import re`
  (already imported at module top).
- `backend/app/routers/ai.py` — remove the unused `db: AsyncSession =
  Depends(get_db)` param from the 12 stateless AI endpoints (grammar_check,
  spell_check, rewrite, status, continue_writing, expand, change_tone,
  analyze, define, change_voice, rewrite_for_clarity, run_generic_tool).
  These never touch the session — currently opens/closes a DB connection per
  AI call for nothing.

### Frontend
- `frontend/src/composables/useAsyncAction.ts` — delete (zero callers).
  *(Stores hand-roll try/catch; see Tier B-note on why we do NOT adopt it.)*
- `frontend/src/stores/entries.ts` — drop `clearError` (no caller).
- `frontend/src/stores/notes.ts` — drop `clearError` and `restoreNote` (no
  caller, no restore UI).
- `frontend/src/stores/email.ts` — drop `resetSelection` (no caller; only
  `clearSelection` is used) and the unread `loadingFolders` ref (never read).
- `frontend/src/stores/tags.ts:36` — drop the `fetchAll` alias (all callers
  use `fetchTree`).
- `frontend/src/components/settings/SettingsView.vue:307` — delete the stale
  `"Sync queue"` search-index entry (panel removed in fe958e4; search now
  highlights nothing).
- Trivial single-expression wrappers to inline (low value, optional):
  `ContactsView.photoFor` (wraps a template literal), `AppShell.showEditor`
  (one-field passthrough). Leave named event-handler wrappers (selectNote,
  onCreated, onClickMessage) — they aid template readability.

---

## TIER B — Safe dedup extractions (behavior-change-risk: no)

### Recommended (local, high-value, low-churn)
- `backend/app/services/spam_service.py` — extract
  `_blocklist_conditions(addr, domain)`; the 5-line addr/domain OR-list is
  rebuilt identically in `is_blocked`, `block_action`, `remove_rules_for`.
- `backend/app/services/analytics_service.py` — extract `_word_count(body)`
  for the `func.length - func.length(replace(...))` fragment used at
  lines 43/117/120/123/126.
- `backend/app/routers/settings.py` — promote the AI field↔attr mapping
  (9 keys) to one module constant used by `_persist_settings`,
  `load_persisted_settings`, `update_app_settings` (currently written 3×).
- `backend/app/services/export_service.py:198` — replace the hand-rolled
  HTML entity decode with stdlib `html.unescape`.
- ~~`frontend/src/utils/error.ts` (new, ~3 lines) — `errMsg(e)` used 11× across
  composables/components; adopt it.~~ **Deferred:** `errMsg` is a *one-line*
  helper (`e instanceof Error ? e.message : String(e)`) duplicated 11×.
  Consolidating means adding an import to 11 files for a trivial function;
  churn/typo risk exceeds the benefit. Left local; flagged here for a future
  pass if the duplication count grows.

### Optional (larger / cross-cutting — propose separately, human pick)
- `useToast` composable — the toast ref+timer+show pattern is copy-pasted
  across ≥6 components. Real consolidation, but adds a composable.
- `frontend/src/utils/format.ts` — date/avatar helpers (formatTime,
  formatFullDate, initialsOf, dateBucket) reimplemented per-component in
  EmailView/Dashboard/Contacts. Variants differ slightly; needs care.
- `downloadBlob` util — verbatim 8-line blob-download in contacts.ts + email.ts.
- `backend routers/sync.py` — three near-identical `on_refresh` closures →
  one helper.
- OAuth routers — `_result_page` (onedrive/dropbox) and `_render_error_page`
  (google_drive/box) duplicated. **Auth-adjacent → require review before
  touch** (flagged in AUDIT, not auto-applied).
- entry/note tag-diff + FTS-search blocks duplicated across entry_service and
  note_service — cohesive but crosses services; a shared mixin is a real
  refactor. Defer unless explicitly approved.
- `encryption_service._get_entry/_get_note` → generic `_get(model, id)`.

### Explicitly NOT doing (boring > clever)
- Not adopting `useAsyncAction` across the 9 stores. Each store's
  loading/try/catch/error block is short, local, and carries a per-store error
  message; a generic wrapper would obscure that. The duplication is accepted.
- Not merging `MediaSizeError` into `ValidationError` — both map to 400 but
  they carry distinct domain meaning; keep.

---

## TIER C — Over-broad error handling (behavior-change-risk: yes → AUDIT, not applied here)

Narrowing these changes which errors propagate (observable behavior), so per
the pipeline rule they are **flagged for the Phase 4 audit, not refactored in
Phase 2.** Listed for record; AUDIT will prioritize.

Backend bare `except Exception` (highest bug-hiding risk):
- `email_service.py:791` (bulk_delete masks data loss), `:959` (send catches
  auth/network/SMTP together), `:1043` (_append_to_special hides append+sync
  failures), `:404` (sync_folder per-folder silent), `:303` (test_connection)
- `backup_service.py:112` (WAL checkpoint), `:260` (whole backup run)
- `cloud_sync_service.py:448` (list_files), `:727` (tarball create)
- `importers/dayone.py:23` (JSON parse), `media_service.py:157` (image
  compression), `storage_service.py:210` (engine rollback), `search_service.py:117`
  (FTS fallback), `routers/ai.py:202` (on_this_day), `routers/settings.py:272`
  (list_ollama_models), `main.py` lifespan blocks.

Frontend `catch {}` silent swallows:
- `api/client.ts:19` (waitForBackend), `stores/email.ts:161/173`
  (refreshCounts/refreshSpamCount), `composables/useAutoSave.ts:88`,
  `useRecordings.ts:74/199/209`, `useUpdateChecker.ts:131`,
  `NoteEditor.vue:100/113/611` (doSave/createTag), `:490` (onPasteTauri),
  `NotesView.vue:82` (loadTags blanks list), `EmailView.vue:370` (bulk spam).

---

## Recommended `--apply` scope

**Tier A (all dead-code removals) + Tier B "Recommended" (5 local extractions +
errMsg).** That's ~15 files, all behavior-change-risk: no, ~120-160 net lines
removed. Tier B "Optional" and Tier C are left for a separate decision / AUDIT.

## After `--apply`
Tests re-run after each unit (backend pytest + frontend build). Any unit that
breaks is reverted and logged here as a false positive.
