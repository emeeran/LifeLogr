# Data-Management Overhaul — Tasks

**Date:** 2026-10-25
**Plan & rationale:** [data-management-overhaul-plan.md](data-management-overhaul-plan.md)
**Conventions:** as in [diarium-enhancement-tasks.md](diarium-enhancement-tasks.md) —
IDs `DM#`, effort **S** ≤ 1 day / **M** 1–3 days; every task ends with
`ruff` + `pytest` green, UI tasks also `vitest`.

Status: DM1 ✅ · DM2 ✅ · DM3 ✅ · DM4 ✅ · DM5 ✅ · DM6 ✅ · DM7 ✅ done — DM8–DM12 pending (2026-10-26).

---

## Tier 1

### DM1 — Remove "On this day" card from calendar · **S** ✅
- **Delete:** `frontend/src/components/calendar/OnThisDayCard.vue` +
  `OnThisDayCard.mount.test.ts`.
- **Unwire:** `CalendarGrid.vue` — import (line ~9), `todayStr` prop usage,
  `fetchOnThisDay()` calls in `loadMonth()`, template usage (~170);
  `stores/entries.ts` — `onThisDayEntries` ref + `fetchOnThisDay` + exports;
  `api/entries.ts:105` `onThisDay()` wrapper; mock in
  `CalendarGrid.mount.test.ts:12`.
- **Keep:** backend `GET /entries/on-this-day`, `entry_service.get_on_this_day`,
  `test_on_this_day.py`, and the daily-reminder count
  (`scheduler_service.py:824-851`) — per plan §DM-B.
- **Accept:** calendar renders with no top strip; no references to
  `OnThisDay` remain in `frontend/src` except none; vitest + pytest green.

### DM2 — Job registry + progress infrastructure · **M** ✅
- **Backend:** `core/jobs.py` — in-memory registry
  (`create_job(kind) -> id`, `update(job_id, phase, done, total, detail)`,
  `finish/fail`, TTL cleanup); `routers/jobs.py` — `GET /api/v1/jobs/{id}`;
  a `ProgressReporter` callback protocol services accept (default no-op so
  existing tests pass unchanged).
- **Frontend:** `composables/useJobProgress.ts` (1 s poll while
  `status == "running"`, stops on finish/fail) +
  `components/common/OperationProgress.vue` (determinate bar + phase label;
  indeterminate mode when `total` unknown; error state).
- **Accept:** unit tests for registry (create/update/finish/TTL) and
  composable (fake timers); component test for both bar modes; registering
  no reporter leaves existing endpoints byte-compatible.

### DM3 — Progress for backup & restore · **M** ✅
- Phases for `run_backup`: checkpoint DB → archive DB → media files
  (done/total) → upload (chunk/byte progress where the provider SDK allows,
  else indeterminate) → retention pruning. Restore: download → extract →
  validate → swap DB → swap media → rebuild engine.
- Local-folder, scheduled "Run now", and cloud `/backup/run` all start jobs
  and return `job_id`; `BackupTab.vue` swaps spinners for
  `OperationProgress` per operation.
- **Accept:** unit test drives `run_backup` with a fake provider + N media
  files and asserts monotonic progress events covering all phases; restore
  progress asserted similarly; UI test renders running → done.

### DM4 — Progress for imports · **S** ✅
- Phases: parse/validate file → stage media (done/total) → insert entries
  (done/total) → enrich/dispatch. Applies to `/entries/import/file`,
  `/entries/import`, notes imports; `ImportExportPanel` shows one progress
  bar for the active import.
- **Accept:** fixture import (Diarium builder + Day One golden zip) reports
  ≥3 phases with done/total monotonic; failure mid-import reports error on
  the job and leaves DB untouched (existing hardening tests stay green).

### DM5 — Progress for exports · **S** ✅
- Phases: collect entries/notes → render bodies → write media members
  (done/total) → finalize archive. Applies to archive ZIP, Markdown ZIP,
  HTML zip, and `.diary` writers; export buttons get
  `OperationProgress`.
- **Accept:** export of a seeded DB with media reports media-file progress;
  small exports (0 media) complete with phases but no division-by-zero/NaN
  in percent.

## Tier 2

### DM6 — Reorganize the Data tab · **M** ✅
- Per plan §DM-C: pills become **Import / Export / Backup & Restore /
  Maintenance / Storage** (Diagnostics reduced to the egress report).
- New panels `ImportPanel.vue`, `ExportPanel.vue`, `BackupRestorePanel.vue`
  (rename/rework `BackupTab.vue` → panel naming consistent with siblings);
  each format row in Export labeled with what it carries
  (entries/media/notes/events) and a one-line "portable export vs full
  instance backup" explainer; notes import/export live in the same panels,
  not a separate section; single "Run now".
- Port existing `tests/settings.spec.ts` Data-tab test; add mount tests per
  new panel.
- **Accept:** every operation reachable before is reachable after (checklist
  in PR description); no duplicate "Run now"/integrity buttons in the tab;
  vitest green.

### DM7 — Deduplicate maintenance/integrity & API wrappers · **S** ✅
- Keep `GET/POST /system/integrity` + `rebuild-search-index`; make
  MaintenancePanel use them and delete `/settings/vacuum`'s sibling
  `/settings/integrity-check` (migrate any callers; keep `/settings/vacuum`
  itself). Move "Rebuild index" + "Re-check" out of DiagnosticsPanel.
- Consolidate export/import URL builders into `api/data.ts` (thin re-exports
  keep `api/backup.ts`/`api/export.ts` importers working or are updated in
  the same commit).
- **Accept:** one integrity endpoint remains; grep shows no orphan callers;
  pytest + vitest green.

### DM8 — Backup/restore completeness tests · **S**
- Round-trip test: seed DB with entries + media + tags + events + notes +
  note attachments → `backup/export` → wipe DATA_DIR → restore → assert all
  rows and media/attachment files byte-identical and FTS rebuilt.
- **Accept:** test covers entries, notes, note attachments, entry media,
  entry events; also asserts the tarball contains every `media/` file.

### DM9 — Native archive v2: notes + attachments · **M**
- Bump `ARCHIVE_FORMAT` to v2: add `notes.json` member + note attachments
  under `media/` in `export_service.build_archive`; importer accepts v1 and
  v2 (keyed on format field), restoring notes + re-attaching files; entry
  events ride along since they're already in `lifelogr.json` (verify).
- Export panel labels native archive as the complete portable export.
- **Accept:** v2 export → fresh DB import reproduces entries+media+notes+
  note attachments+events; a v1 fixture still imports; schema-upgrade test
  not required (no DB schema change).

### DM10 — `.diary` writer fidelity · **M**
- In `export_service._build_diarium_database_sync` (plan §DM-E): real
  local-datetime ticks with collision offset (fixes same-day PK collision);
  write `Events` from `entry_events` (`Type=0` weather; unknown kinds
  skipped + logged); write tracker tags `Type=2` + `EntryTags.TrackingValue`
  verbatim; media GUID ids, `"Index"`, `Name`/`FileEnding`, full type map;
  `user_version=4`, `journal_mode=delete`, `sqlite_sequence` upkeep,
  empty `Templates` table; verify Rating/Lat/Long round-trip.
- **Accept:** writer output validated against the format-analysis schema
  (see DM11); two-entries-same-day fixture no longer collides.

### DM11 — `.diary` round-trip + structural validation suite · **M**
- New `unit/test_diarium_roundtrip.py`: synthetic `.diary` (existing
  `tests/helpers/diarium_diary.py`, extended for trackers/events/type-2
  media) → lifelogr import → `.diary` export → re-import; assert content
  equivalence modulo markdown/HTML conversion. Structural validator helper
  asserting exported files match `diarium-format-analysis.md` §2 schema +
  §3 encodings (ticks sane, `FileEnding` dotted, `Index` dense from 0,
  blob magic matches `Type`).
- **Accept:** round-trip lossless for the fixture; validator fails on a
  deliberately corrupted export (negative test).
- **Manual (you):** import a lifelogr-exported `.diary` into Diarium on a
  real device and confirm entries/media/tags render (tracked as DM12).

## Tier 3

### DM12 — Docs + manual Diarium compatibility check · **S**
- Update the user manual's Data section (new panel layout, progress UX,
  "what each format carries" matrix), `ARCHITECTURE.md` data-management
  section, and this doc's status line.
- Manually: open lifelogr's exported `.diary` in Diarium; import the real
  `Diarium.diary` backup again and spot-check media/trackers.
- **Accept:** docs merged; manual check results recorded here.

---

## Suggested order

```
DM1 → DM2 → DM3 → DM4 → DM5 → DM6 → DM7     progress + reorg spine
DM8 any time; DM9 → DM10 → DM11 in parallel with the spine
DM12 last
```
