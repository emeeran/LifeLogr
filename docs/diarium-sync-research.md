# Syncing Diarium ⇄ LifeLogr (entries + attachments)

Research note, 2026-11-07. Question: journaling happened across Diarium (Android),
Diarium (Windows) and LifeLogr — what is the best way to get everything, attachments
included, into one synced state?

## 1. TL;DR

- **A live, automatic two-way sync with Diarium is not possible.** Diarium has no API,
  no backend and no account; its Cloud Sync transports **compressed + encrypted** blobs
  that the vendor explicitly says other programs must not read or write. There is nothing
  to hook into.
- **File exchange is the only supported channel**, and Diarium has *two different* import
  doors with opposite semantics:
  - `Import diary` (`.diary` backup) → **replaces** the whole journal. Lossless, includes media.
  - `Migrate from other app` (Day One JSON `.zip`) → **adds** entries and **skips**
    date/times that already exist. Does **not** overwrite. This is the attachment-capable
    incremental path, and it is the one the Diarium developer recommends for scripted imports.
- **LifeLogr already speaks both directions of the pull path.** Implemented since
  this note was written: merge-mode `.diary` import (source identity, hash-based
  media repair, conflict reporting) and the Day One ZIP exporter for the push leg.
- **Current local state shows why the merge mattered:** the Diarium backup holds 237
  attachments (197 MB), the LifeLogr database holds **7** media rows (19.8 MB).
  The text merged; the photos and voice notes did not.

## 2. How Diarium actually works (verified)

### 2.1 Storage and sync

| Fact | Source |
|---|---|
| Journal is local to each device; no Diarium account, no server-side copy | Diarium help + forum FAQ |
| Cloud Sync (Pro) uses *your* OneDrive / Google Drive / Dropbox / iCloud / WebDAV | Diarium help |
| Sync data is **compressed and encrypted**, unreadable by other apps; vendor says do not modify or rename those files | forum.diariumapp.com/d/13 |
| Sync folders: OneDrive `Applications/Diarium`, Google Drive/WebDAV `Diarium/`, Dropbox `Apps/Diarium`, iCloud hidden | same |
| Editing the same entry concurrently is not supported — "finish editing and let sync complete on one device before editing on another" | Diarium help |
| No API, no webhooks, no "share structured data into Diarium" endpoint | developer, forum d/4854 |

**Consequence:** Syncthing/Dropbox tricks on the *database* or on Diarium's sync folder are
an anti-pattern — the payload is opaque, and concurrent writers corrupt state. Never sync
`lifelogr.db` and a Diarium database as if they were the same file.

### 2.2 The `.diary` backup (lossless, restorable)

Real file inspected: `~/Downloads/backup/Diarium.diary` (SQLite, `user_version=4`,
190 MB, 1393 entries, 237 media rows totalling 197,706,026 B, 40 tags, 134 entry-tags,
161 events, date span 2008-02-22 → 2026-06-12).

```
Entries  (DiaryEntryId PK, Heading, Text, Rating, Latitude, Longitude)
EntryTags(DiaryEntryId, DiaryTagId, TrackingValue)
Events   (DiaryEventId, Type, Content, Tag, DiaryEntryId)
Media    (DiaryMediaId, Type, Data BLOB, Name, FileEnding, "Index", DiaryEntryId)
Tags     (DiaryTagId, Value, Type, Color, Icon)   -- Type 0 tag, 1 person, 2 tracker
Templates(TemplateId, Name, Heading, Text, Tags)
```

Three properties drive the whole design:

1. **`DiaryEntryId` *is* the timestamp** (.NET ticks, 100 ns since 0001-01-01). It is the
   only identity an entry has.
2. **There is no `LastModified` / `CreatedAt` / `UpdatedAt` column** and no tombstones.
   External tooling cannot tell "edited" from "unchanged", and cannot see deletions at all.
3. **Media are rows, not files** — blobs live in `Media.Data`, ordered by `"Index"`.
   Type: 0 image, 1 audio, 2 unknown, 3 document, 4 video/audio-attachment.

Because of (1) and (2), any sync must be **snapshot reconciliation with a local ledger**,
not change-feed replication.

### 2.3 What Diarium can export / import

| Direction | Format | Media | Semantics |
|---|---|---|---|
| Export | `.diary` backup | ✅ blobs | Complete; restorable |
| Export | JSON | ❌ none — open bug/report: "Attachments" checkbox has no effect, not even filenames | Readable data only |
| Export | HTML | ✅ embedded | Human-readable |
| Export | plain text | ❌ | Human-readable |
| Export | Word (Pro) | ✅ | Human-readable |
| Import | `Import diary` (`.diary`) | ✅ | **Replaces** the journal |
| Import | `Migrate from other app` | ✅ for Day One | **Adds**, and **skips entries whose date/time already exists** |

Developer statements (forum d/4854, May 2025 – May 2026):

> "targeting the Day One JSON export format is probably the best option currently,
> especially if you want to include attachments."
>
> "Diarium does not download images from remote URLs during import. The media files need to
> be included in the imported .zip file … For Day One-style imports, Diarium uses the
> attachment `md5` fields in the JSON and looks for files in the archive whose filenames
> start with that md5 value."
>
> "Existing Diarium entries are not overwritten; entries with an already existing date/time
> are skipped."

`Migrate from other app` lists Day One, Journey, Diaro and Apple Journal. LifeLogr is not
listed, and raw LifeLogr JSON is not importable — it must be shaped as Day One.

## 3. What LifeLogr has today

Implemented (`backend/app/services/importers/`, `export_service.py`):

- **Import:** Diarium `.diary` (media blobs, events, tracker readings, person tags),
  Diarium-shaped JSON, Day One `.zip`, Markdown `.zip`, Daylio CSV, native archive.
- **Export:** Diarium `.diary` (schema-identical, media blobs, verified restorable),
  Diarium-shaped JSON, Daylio CSV, Markdown/HTML `.zip`, native archive (`lifelogr.json` + `media/`).
- `.diary` writer emits `DiaryEntryId = midnight UTC of entry_date`, +1 s per extra
  same-day entry (`_build_diarium_database_sync`).

Status of those gaps (2026-11-07):

| Gap | Status |
|---|---|
| **No external identity** | **Done.** `entries.external_source` / `external_id` (Diarium ticks) / `external_updated_at` / `sync_hash`, migration `_SCHEMA_VERSION=3`, partial unique index `ix_entries_external`. |
| **No merge on import** | **Done.** `mode=merge` (default) matches by source id, then by `date + body[:1000] + mood` to adopt the 1393 legacy rows; text is updated only when `sync_hash` proves the local copy is untouched; anything ambiguous is reported as a conflict and local text is kept. `mode=append` preserves the old behaviour. |
| **Media dedupe was all-or-nothing** | **Done.** Attachments are compared by sha256 content multiset, so a partially lost entry is repaired and deliberately duplicated photos survive. |
| **No Day One exporter** | **Remaining** — the next build step for the push leg. Only a parser exists today. |
| **Heading-only entries dropped** | **Fixed** — a heading with an empty body is content; the `elif` that skipped it is gone. |
| **Deletions invisible** | **By design.** Diarium has no tombstones. A soft-deleted LifeLogr row is never resurrected by a pull and never pushed as a delete. |

### 3.1 Measured current state

| | Diarium backup | LifeLogr DB |
|---|---|---|
| Rows | 1393 | 4134 (2741 soft-deleted) → **1393 live** |
| Distinct days | 1180 | 1180 (**1165 overlap**) |
| Date span | 2008-02-22 → 2026-06-12 | 2019-05-19 → 2026-07-14 |
| Media | 237 (189 MiB) | **7 (19.8 MB)** |

The 15 Diarium days absent from LifeLogr are 14 empty `Today's Summary` placeholders
(correctly skipped) plus the heading-only entry above. So **the text is essentially merged
already; the attachments are the real outstanding loss.** Note the on-disk backup also stops
2026-06-12 while "today" is 2026-11-07 — a fresh export is needed before any reconciliation.

## 4. Options

### Option A — Consolidate: LifeLogr becomes the system of record *(recommended for "all in one place")*

1. Take a fresh `.diary` from **each** Diarium installation (mobile, Windows). If Diarium
   Cloud Sync is on, one backup covers all devices; if not, they are two divergent journals
   and both must be imported (entry ids are globally unique, so the union is clean).
2. Import into LifeLogr **in merge mode** (needs the identity work below), which fills in the
   230 missing attachments and adds the 5 months after June.
3. Keep Diarium read-only from then on — or run one final `.diary` export into Diarium as an
   archive.

- ✅ Simplest, no ongoing file juggling, no conflict model.
- ❌ Diarium users lose the mobile app's capture convenience; any later Diarium writing has
  to be re-imported manually.

### Option B — Incremental two-way over files, with a sync ledger *(recommended if Diarium stays in use)*

Two independent half-syncs, each using Diarium's supported door:

- **Pull (Diarium → LifeLogr):** user produces `Diarium.diary` (Settings → Backup diary).
  LifeLogr imports in **merge mode**: match on stored `diarium_entry_id`, else
  (date + normalized-body hash); update body/tags/rating/geo, attach any media whose
  hash is not present, never delete.
- **Push (LifeLogr → Diarium):** LifeLogr exports a **Day One JSON `.zip`** containing only
  entries Diarium has not seen (ledger watermark), with photos named `<md5>.<ext>`.
  User: Settings → Migrate from other app → Day One. Diarium adds them and skips collisions.

- ✅ Non-destructive in both directions; uses only vendor-supported routes; no crypto games.
- ✅ Push is append-only by construction, which matches Diarium's importer.
- ❌ Edits made to an *existing* entry are not pushed (Diarium skips it). Mitigation: "changed
  since last sync" entries are pushed as a **new** day-entry (a conflict copy) rather than
  silently lost — or escalated to Option C deliberately.
- ❌ Manual step per sync (two file hand-offs). Can be reduced on the desktop side by a
  watched folder, but Android/iOS always need a share sheet.

### Option C — Full-journal round trip through `.diary` *(only when you must propagate edits/deletes)*

LifeLogr `export/diarium-db` → Diarium `Import diary` (replaces the journal) → Cloud Sync
fan-out. Schema-identical and media-complete, so this is the only route that carries **edits
and deletions** into Diarium.

- ✅ Total convergence; `user_version=4` and all six tables verified.
- ❌ **Destroys any Diarium-side work done after the export** (import replaces, not merges).
- ❌ Rewrites every `DiaryEntryId` to midnight UTC → time-of-day is lost and each device
  re-uploads ~190 MB on the next sync.
- ❌ Never run this while a phone holds unsynced edits.

### Rejected

- Reading/writing Diarium's Cloud Sync blobs: encrypted, undocumented, breaks on update,
  and the vendor warns against it.
- Reading a live Diarium SQLite DB while the app runs: WAL contention, and it still gives
  read-only access with no change tracking.
- Treating Daylio CSV as the sync format: text/mood only, no media, no identity.

## 5. Recommended design (Option B, detailed)

### 5.1 Identity

Add to `entries` (via `_COLUMN_MIGRATIONS` in `core/database.py`):

- `external_source TEXT NULL` — `'diarium'` / `'dayone'` / … 
- `external_id TEXT NULL` — the Diarium `.NET` ticks as a string (int64 exceeds JS safety)
- `external_updated_at DATETIME NULL` — Diarium has none; store the **backup file's** mtime,
  used only as a tiebreak/watermark
- `sync_hash TEXT NULL` — sha256 of (heading, canonical text, rating, lat/long, sorted tag
  names+types, sorted media hashes)
- index `(external_source, external_id)` unique-where-not-null

Importers set these; exporters emit `external_id` verbatim instead of deriving from date.
Everything degrades gracefully for rows with no identity (legacy imports).

### 5.2 Pull (merge-mode import)

For each parsed Diarium entry, in order:

1. `external_id` match → reconcile in place (metadata fill, then update only if `sync_hash`
   shows the local copy is untouched).
2. Else match on `(entry_date, body[:1000], mood)` among rows with no `external_id`
   → adopt the identity (this is what retro-fits the 1393 existing rows without duplicates).
3. Else create, with `external_id` set.
4. Media: for each `.diary` `Media` row compute sha256 of the blob and compare against a
   per-entry digest multiset; insert only what is missing. This makes re-import idempotent
   and back-fills the missing 230 attachments.
5. Never delete. Report "in Diarium but not in LifeLogr" only as diagnostics.

Exposed as `POST /api/v1/entries/import/file?mode=merge` (the default; `mode=append` keeps
the old always-insert behaviour), returning
`{imported, updated, skipped, media_backfilled, conflicts, skip_reasons}`.

### 5.3 Push (Day One exporter) — **implemented**

Route `GET /api/v1/entries/export/dayone-zip`, builder `_build_dayone_zip_sync`:

```
Journal.json                     # {"metadata": {...}, "entries": [...]}
photos/<md5>.<ext>               # media, filename MUST start with the JSON's md5
```

Per entry: `creationDate` (noon UTC — LifeLogr stores a date, and noon cannot roll into an
adjacent day on timezone conversion), `text`, `title`, `tags`, `location`, and
`photos:[{md5,type,filename,size,caption}]`; `uuid` is a uuid5 of the entry id, so
re-exporting is stable. Encrypted entries are skipped and counted in `metadata`.

Delta selection needs no ledger yet: `scope=new` (default) takes rows with `external_id IS
NULL` whose date is not covered by a Diarium-sourced row, which is exactly "entries Diarium
has never received". On the real backup this selected 15 of 1,400 entries. A ledger would
only avoid re-sending entries the user already imported on the Diarium side (Diarium's own
date/time skip prevents duplicates), so it is a bandwidth optimisation, not correctness.

### 5.4 Conflicts and deletions

- Both sides changed since the last sync → keep both: the LifeLogr row is pushed as a
  conflict copy titled `⧉ conflict <title>`. Never silently drop text.
- LifeLogr soft-delete → **not propagated**. Diarium cannot represent a deletion, and its
  importer cannot remove entries. Deletions in Diarium are likewise invisible; the merge
  simply re-adds entries that reappear in a later backup.
- Media orphaned by a delete stays on disk (existing soft-delete cleanup applies only to
  LifeLogr-side deletes).

### 5.5 Implementation checklist in this repo

1. ✅ `core/database.py` → column migrations + partial unique index (`_SCHEMA_VERSION=3`).
2. ✅ `models/entry.py` → columns and the model-declared index (fresh DBs via `create_all`
   and migrated DBs converge).
3. ✅ `services/importers/diarium.py` → carries `external_id` + backup mtime; heading-only
   entries no longer dropped.
4. ✅ `routers/entries.py` `_run_entry_import` → `mode=merge` (match → adopt → update),
   hash-multiset media repair, additive tags/events, conflict reporting.
5. ✅ Day One writer (`_build_dayone_zip_sync` in `export_service.py`) + route
   `GET /entries/export/dayone-zip` (`scope=new|all`) + Data-tab row. Delta
   selection uses the identity columns (`scope=new`), so no ledger is needed yet.
6. ⬜ Ledger model + `services/diarium_sync_service.py` if pushes need to stop
   re-sending already-delivered LifeLogr entries (Diarium's date/time skip covers
   correctness today; this would only save bandwidth).
7. ◐ Frontend: the Data tab has the **Day One ZIP (Diarium push)** row with a
   *Only new / All* selector. A dedicated "Diarium sync" panel showing
   `created / updated / media added / skipped / conflicts` after a pull is still open.
8. ✅ Tests: `tests/integration/test_import_diarium_merge.py` covers double-import
   idempotency, partial media repair, source-edit propagation, local-edit conflict, and
   `mode=append`; `tests/integration/test_export_dayone.py` covers the ZIP shape
   (md5-named members, noon-UTC dates), our own parser reading it back, `scope=new`,
   encrypted skipping, and UUID stability.

## 6. Verify on real devices before coding the push

These are the assumptions that could invalidate Option B's push leg:

1. Does Diarium's skip test use the full date+time or only the date? Export two entries on
   one day to find out. If it is date-only, the ledger must exclude whole days, not timestamps.
2. Does the Day One importer honour `creationDate` timezone offsets, or normalise to local?
3. Which Day One keys does it actually read (`text` vs `richText`, `tags`, `location`,
   `photos[].type`)? Confirm against a genuine Day One export from Diarium's own list.
4. Whether `<md5>.<ext>` prefixes satisfy the match rule for audio/video/PDF too.
5. Whether Diarium dedupes identical media if the same file is imported twice under a
   different entry.

## 7. What can be done today

**Pull (Diarium → LifeLogr)**

1. In Diarium: Settings → **Backup diary** on the device with the newest data.
2. LifeLogr: back up first (`Settings → Data → Backup` producing `lifelogr-backup-*.tar.gz`).
3. Import the `.diary` (`Settings → Data → Import`). Since the merge landed this is
   **repeatable and safe**: unchanged entries are skipped, missing attachments are
   restored, source edits apply to locally untouched entries, and local edits are kept
   and reported as `conflicts`. Run it once per Diarium device if Cloud Sync was never on.

**Push (LifeLogr → Diarium)**

4. In LifeLogr: Settings → Export → **Day One ZIP (Diarium push)** → *Only new* → Export.
5. In Diarium: Settings → **Migrate from other app** → **Day One** → pick the ZIP.
   Entries and their photos/attachments are added; anything Diarium already has is skipped.
6. Use *All* instead of *Only new* only for a deliberate one-way archive.

Use the `.diary` export → Diarium `Import diary` only when you want Diarium's journal
*replaced* by LifeLogr's copy (it does not merge, and rewrites every timestamp to midnight).

The remaining work for a fully automatic loop is a push ledger (bandwidth only) plus
the §6 device checks.

---

### Notes / loose ends

- `docs/diarium-format-analysis.md` is cited by `ARCHITECTURE.md`, `tests/helpers/diarium_diary.py`
  and `importers/diarium.py` but no longer exists in the tree — worth restoring, since the
  schema claims above depend on it.
- Diarium mobile is Pro-gated for Cloud Sync; the Windows app includes it. Attachment limits:
  free mobile = 1 per entry, Windows and Pro = unlimited.
