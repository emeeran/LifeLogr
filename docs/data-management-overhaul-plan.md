# Data-Management Overhaul — Plan

**Date:** 2026-10-25
**Companion:** [data-management-overhaul-tasks.md](data-management-overhaul-tasks.md)
(task list with acceptance criteria) ·
[diarium-format-analysis.md](diarium-format-analysis.md) (`.diary` ground
truth) · [ADR-004](04-design/ADR/004-filesystem-media-storage.md) (media on
filesystem) · [ADR-005](04-design/ADR/005-background-tasks-for-backup.md)
(background-task precedent).

Task IDs are `DM#`. Suggested branch: `feature/data-management-overhaul`
(current `feature/on-this-day` is done and can be merged first, since DM1
removes part of what it shipped).

---

## 0. Scope (from the request)

1. Remove the "On this day, N years ago…" strip from the calendar top row.
2. Realtime progress indicators for backups, imports, and exports.
3. Remove redundant tools in Data & Database management; consolidate and
   reorganize export/import and backup/restore.
4. Guarantee media, journals, and notes are included in exports/imports and
   backup/restore.
5. Guarantee `.diary` is fully compatible in both directions with LifeLogr
   **and** Diarium, with all media, journals, and notes carried.

## 1. Current state (verified)

- **No Rust data logic.** All backup/import/export/maintenance is the Python
  FastAPI backend (`backend/app`); the Tauri shell and the web build share the
  same Vue frontend + backend.
- **One data surface:** Settings → Data tab (`DataTab.vue`) with 5 pills:
  Storage / Import-Export / Backups / Maintenance / Diagnostics.
- **Backup/restore is already complete in content:** `GET /backup/export`
  tars the whole SQLite DB (`diarium.diarium`) + `media/`; restore swaps DB
  and media atomically (`core/restore.py`). Since notes live in the DB and
  note/entry attachments live in `media/`, a backup already carries all three
  — but nothing tests or documents that.
- **No progress mechanism exists** for data ops. Only precedent is the Ollama
  model-pull job dict polled via `GET /pull-model/{job_id}`
  (`routers/ai.py:269`). Frontend uses per-button spinners and raised request
  timeouts.
- **Known redundancies:** integrity check implemented twice
  (`/settings/integrity-check` vs `/system/integrity`); "Run now" backup in
  two places; "Archive ZIP (entries+media)" (Import-Export pill) vs "Local
  archive .tar.gz (DB+media)" (Backups pill) with no user-facing explanation
  of the difference; export/import API wrappers spread over 5 modules;
  `BackupTab.vue` named a tab but is a panel.
- **`.diary` writer gaps** (vs the format analysis): entry IDs are ticks of
  the entry date at 00:00 UTC — so two entries on one calendar day collide on
  the `DiaryEntryId` primary key, and time-of-day is lost; `Events` (weather)
  and tracker tags (`Tags.Type=2` + `TrackingValue`) are not written; no
  round-trip test.

## 2. Design decisions

### DM-A · Progress: polled jobs, not WebSockets (recommended)

There is no WS/SSE infra, the Ollama pull already established the in-process
job-dict + polling pattern, and ADR-005 already runs data ops in background
tasks. Add one generic mechanism instead of three:

- `POST`-initiated long ops return `{job_id}`; `GET /api/v1/jobs/{id}` →
  `{status, kind, phase, percent, detail, error}`. Jobs live in an
  in-memory registry with TTL cleanup (single-process backend, like the
  pull-model jobs).
- Services report progress through a `ProgressReporter` callback
  (phase + done/total) so backup, import, and export services stay
  transport-agnostic and unit-testable.
- Frontend: a `useJobProgress(jobId)` composable (1 s poll while active) and
  one `<OperationProgress>` component (determinate bar with phase text,
  indeterminate when total unknown), replacing per-button spinners on
  backup/restore/import/export buttons.
- Backup/restore already run in background tasks — attach job ids there.
  Imports/exports become job-started when large (media count above a
  threshold) or always, for one uniform UX.

Rejected: SSE (new transport, no reconnect story in the Tauri sidecar setup),
WebSocket (same, plus more surface), Tauri events (web build must work too).

### DM-B · Calendar consolidation

Remove `OnThisDayCard.vue` from `CalendarGrid.vue` plus its store wiring
(`onThisDayEntries`, `fetchOnThisDay`) and its mount test. **Keep** the
backend `GET /entries/on-this-day` endpoint, its tests, and the daily-reminder
"on this day" count — they are independent surfaces with test coverage, and
the endpoint is the natural base for a future home-screen card. (If you'd
rather remove the API too, it's a small follow-up: delete the router block,
service method, and `test_on_this_day.py`.)

### DM-C · Data tab reorganization

Five overlapping pills → four clean ones:

| New panel | Contents |
|---|---|
| **Import** | Entries (Diarium `.diary`/JSON, Day One, native archive, CSV, Markdown, HTML) + Notes (native, Markdown ZIP) — one panel, shared job progress |
| **Export** | One list of formats, each labeled with what it carries (entries / media / notes / events); includes the full-data **native archive** and **.diary**; notes exports merged here |
| **Backup & Restore** | Local archive (.tar.gz, DB+media) backup/restore, scheduled backup, cloud configs & snapshots — single "Run now" |
| **Maintenance** | Deduplicate, vacuum, integrity check, rebuild search index (absorbed from Diagnostics), reset/erase pointers unchanged in About |

Storage stays its own pill (or moves to Maintenance — either is fine; tasks
assume it stays). Diagnostics shrinks to the egress report. The "Archive ZIP
entries+media vs Local tar.gz DB+media" confusion is resolved by labeling:
the native archive is presented as the *portable* export (imports anywhere,
including other lifelogr instances), the tar.gz as the *full-instance*
backup.

### DM-D · Completeness guarantee (media + journals + notes)

- **Backup/restore:** already carries everything (DB + `media/`). Add the
  missing proof: round-trip tests asserting entries, tags, events, notes,
  note attachments, and entry media survive backup → wipe → restore.
- **Native archive export/import:** extend `ARCHIVE_FORMAT` to v2 adding a
  `notes.json` member + note attachment files under `media/` (v1 archives
  still import — importer keys off the format field). This becomes the one
  "everything" portable export; the Export panel labels each other format
  with what it omits.
- **Notes standalone exports:** verify attachments are embedded in the
  Markdown ZIP and JSON exports; add them if not.

### DM-E · `.diary` bidirectional fidelity

Target: a `.diary` written by lifelogr opens in Diarium with entries, media,
tags, trackers, and weather intact; importing it back into lifelogr
reproduces the same content (markdown/HTML conversion excepted). Work items:

1. **Fix PK collisions:** encode the entry's actual local datetime (not
   00:00 UTC) as .NET ticks, matching Diarium's local wall-clock convention
   (format analysis §3.1); append an incrementing offset when two entries
   share the exact timestamp.
2. **Write `Events`** from `entry_events` (D2 weather, `Type=0`; unknown
   kinds preserved with a logged skip since the enum beyond 0 is unverified).
3. **Write trackers:** `Tags.Type=2` + `EntryTags.TrackingValue` verbatim.
4. **Media:** GUID `DiaryMediaId`, `"Index"` ordering, `Name` without
   extension + `FileEnding` with dot, full type map incl. `2`.
5. **Container details:** `user_version=4`, `journal_mode=delete`,
   `sqlite_sequence` maintained, `Templates` table present (may be empty).
6. **Round-trip test:** synthetic fixture (from the existing
   `tests/helpers/diarium_diary.py` builder) → import → export → import;
   structural validator asserting the exported file matches the documented
   schema and invariants. Diarium-side acceptance is a manual check by you on
   a device (we can't run Diarium here); the structural validator is the
   automated proxy.

**Explicitly out of scope:** notes in `.diary` (Diarium has no notes concept
— notes travel via the native archive), Diarium's encrypted cloud-sync
payload, Templates round-tripping.

## 3. Sequencing

```
DM1  remove on-this-day card (S)          — independent, do first
DM2  jobs + progress infra (M)            — prerequisite for DM3–DM5
DM9  archive v2 (M)                       — independent of DM2
DM10 .diary writer fidelity (M)           — independent of DM2
DM11 .diary round-trip suite (M)          — after DM10
DM3  progress: backup/restore (M)         — after DM2
DM4  progress: imports (S)                — after DM2
DM5  progress: exports (S)                — after DM2
DM6  data-tab reorganization (M)          — after DM3–DM5 (panels land finished)
DM7  maintenance dedupe (S)               — before/with DM6
DM8  completeness tests for backup (S)    — anytime
DM12 docs + manual Diarium check (S)      — last
```

Parallelizable pairs: (DM9, DM10) and (DM3–DM5) once DM2 lands.
