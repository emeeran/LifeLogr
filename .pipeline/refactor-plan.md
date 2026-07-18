# Phase 2 — Debloat & Refactor (DRY-RUN PLAN)

Generated for branch `cleanup/pipeline-2026-07-18`, 2026-07-18. **No code changed yet.**
Each row has a before/after rationale; safe items act on `--apply`, behavior-risk items
are flagged for `AUDIT.md` (not refactored blindly). All findings were verified by the main
thread (`git grep`) before inclusion — false positives from the scanning agents are listed
under "Rejected."

Scan method: 3 parallel read-only subagents (backend services+routers; backend
core/schemas/models/tests; frontend src), each told the bar is HIGH (repo already debloated
2026-07-12 and 2026-07-18) and to mark behavior-change risk explicitly. Main thread verified
every load-bearing claim.

## Headline

The backend **core / schemas / models / tests are clean** — the scanning agent's 20 "model
inheritance" hits were fabricated and its remaining flags were verified as intentional
boundary handling (FTS5/init degrade-gracefully blocks, test teardown). Nothing actionable
there. Real bloat is concentrated in two places: **frontend dead response-types + the
`errMsg` one-liner duplicated 18×**, and **a few backend deduplication wins**. Plus one
**latent backend inconsistency** (cloud-provider construction drift) that is a bug
masquerading as duplication → audit, not blind merge.

---

## SAFE to refactor on `--apply` (behavior-change risk: none / low)

### Frontend

| # | location | what | rationale | risk |
|---|----------|------|-----------|------|
| F1 | `frontend/src/types/index.ts` (~11 types) | delete dead response types | `GrammarCheckResponse`, `SpellCheckResponse`, `ContinueWritingResponse`, `ChangeToneResponse`, `AnalyzeTextResponse`, `DefineTextResponse`, `VoiceChangeResponse`, `RewriteForClarityResponse`, `VideoNoteResponse`, `SyncQueueItem`, `BlockSenderResult` — all 0 external refs (5 spot-verified). Likely remnants of AI features that ship other response shapes. | none |
| F2 | `frontend/src/**` (16 files, 18 occurrences) | extract `errMsg(e: unknown): string` → `frontend/src/utils/error.ts`; import everywhere | `e instanceof Error ? e.message : String(e)` re-derived 18× (EmailView, EntryEditor, NoteEditor, 6 settings panels/tabs, 3 composables, tts store). The classic AI-tell. | none |
| F3 | `frontend/src/composables/useEditorHistory.ts:58-60` | drop dead `const el = textarea.value` + `void el` | `el` is assigned, never read; `void el` is an eslint-appeasement no-op. | none |
| F4 | `frontend/src/composables/useAiTools.ts:7` | remove `export { AI_TONE_OPTIONS } from './aiToolRegistry'` | re-export has no external consumer (only used inside `aiToolRegistry.ts`). | none |
| F5 | `frontend/src/components/settings/tabs/FeaturesTab.vue:54` | `import { isTauri } from '../../../api/client'` instead of re-deriving | `const isTauri = !!(window as any).__TAURI_INTERNALS__` duplicates `api/client.ts:3` (used correctly by 4 other files). | none |
| F6 | 4 files: `DashboardView.vue:215`, `EncryptionBadge.vue:48`, `AppShell.vue:110`, `BackupTab.vue:380` | `catch (e: any)` → `catch (e: unknown)` + `e instanceof Error` | rest of codebase standardised on `unknown`; these are stragglers. | none |
| F7 | `frontend/src/components/settings/tabs/BackupTab.vue:408` | static import of `request` instead of `await import("../../../api/client")` | unnecessary dynamic import; module already in bundle via siblings. | none |
| F8 | `frontend/src/components/common/EmojiPicker.vue:224-228` | implement emoji-name search OR remove the non-functional search input + `filterEmojis` | the search box is decorative — `filterEmojis()` returns `emojis` unchanged when there's a query (comment admits it). Dead branch. | low |

> `frontend/src/components/common/EditorButton.vue` and `StateView.vue` are dead **files** —
> handled by Phase 1 purge (move to `trash2review`), not here.

### Backend

| # | location | what | rationale | risk |
|---|----------|------|-----------|------|
| B1 | `calendar_sync_service.py:39-101` + `tasks_sync_service.py:35-72` | extract `_mark_synced`, `_local_tz`, `_gdt_to_local`/`_local_to_gdt` → `app/services/google_sync_utils.py` | bodies are byte-identical; the tasks docstring even says "See CalendarSyncService._mark_synced for rationale." | none |
| B2 | `ollama_service.py` (`_parse_grammar_response` ~:461 + `_parse_json_response`) | extract `_extract_json(raw) -> str`; call from both | "strip to outer braces" slicing re-derived in the sibling parser. | none |
| B3 | `routers/dropbox.py`, `onedrive.py`, `google_drive.py`, `box.py` | one `app/routers/_oauth_result_page(title, message, success)` helper for the OAuth success/failure HTML | each router hardcodes its own inline-CSS HTML page (~70 lines in google_drive alone), differing only in copy/branding. | low (verify each page's exact copy preserved) |

---

## BEHAVIOR-RISK → flag in `AUDIT.md`, do NOT blindly refactor

| # | location | what | why it's risky |
|---|----------|------|----------------|
| R1 | `backup_service.py` (`run_backup` :137-252, `_cloud_provider_for` :278-328) vs `routers/sync.py:86-123` (`_get_provider`) | cloud-provider + token-refresh callback constructed in 3 places; `_cloud_provider_for` was *meant* to centralize it (docstring :282) but `run_backup` and `sync._get_provider` don't use it | **`routers/sync.py:92` diverged**: it calls `encrypt(...)` + `await db.flush()` and omits the `reencrypt(...)` wrapper `backup_service` uses — the two paths persist credentials differently. Unifying is correct but must deliberately pick which behavior wins. **Latent bug masquerading as duplication.** |
| R2 | `frontend/src/components/entry/EntryEditor.vue:343-347` | `onUnmounted` calls `window.removeEventListener("click", () => {...})` with a **fresh** arrow — can never match the listener registered at :320 | real listener (AI-dismiss + decrypt-on-click) is never removed → leaks across unmount/remount. Fix = hoist handler to a named const; changes listener lifecycle, needs a remount smoke-test. |

---

## Rejected (verified false positives)

| claim | reality |
|-------|---------|
| `backend/app/routers/ai.py:78` `embed_available` dead | **returned** at `ai.py:87` (`embed_model_available=embed_available`). Live. |
| `backend/app/services/tag_service.py:115` `get_entry_count` superseded/dead | **called** at `routers/tags.py:26`. Live. *(Whether that call site is an N+1 is a Phase-4 audit question, not debloat.)* |
| 20× "model missing inheritance" in `app/models/*` | fabricated — every model correctly inherits `Base`. |
| `_exc_message`, `SyncService`, `_checkpoint_wal_robust`, `_to_response` helpers | verified legitimate WHY-code / multi-use, not bloat. |
| `EncryptionBadge.vue` vs `NoteEncryptionBadge.vue` merge | ~85% similar but med-risk for marginal gain; not recommended unless encryption UX is touched anyway. |

---

## After --apply

Per the command, apply unit-by-unit with a test re-run after each: `uv run pytest tests/ -q`
(backend) after B1–B3, `npm run build` (frontend, catches dead imports/types) after F1–F8.
R1/R2 are NOT in the apply set — they land in `AUDIT.md` for a deliberate decision.
