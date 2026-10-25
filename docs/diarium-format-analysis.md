# Diarium `.diary` Backup Format — Analysis

**Date:** 2026-10-25
**Artifact:** `/home/em/Downloads/backup/Diarium.diary` (189.5 MB)
**SHA-256:** `b2de41f6bb7bd6f92d8a5a73f252611cb321f0037698116d6ebc4e2b6f3cdac7`

**Method:** All observations come from ordinary shell tools (`file`, `sqlite3`,
`python3`) in read-only mode (`mode=ro&immutable=1`) — no REA session was
active and none was needed: the file is an unencrypted SQLite database, so
static SQL inspection gives full structural coverage. Conclusions are
inferred from a **single real-world backup**; enum values not exercised by
this file are marked unknown rather than assumed.

---

## 1. Container

| Property | Value |
|---|---|
| Format | SQLite 3 database, unencrypted |
| `PRAGMA user_version` | 4 |
| Written by | SQLite 3.50.0 (per header) |
| Page size / encoding | 4096 bytes / UTF-8 |
| Journal mode | `delete` (rollback journal, not WAL) |
| Total pages | 48,521 (~190 MB, dominated by `Media.Data` blobs) |

The `.diary` file is exactly the app's SQLite store — Diarium's "backup"
produces the raw database with no container, compression, or encryption
layer. Any tool that can read SQLite can read it.

## 2. Schema (6 user tables)

```sql
Entries(DiaryEntryId bigint PK, Heading varchar NOT NULL,
        Text varchar NOT NULL, Rating integer NOT NULL,
        Latitude float NOT NULL, Longitude float NOT NULL)
EntryTags(DiaryEntryId bigint, DiaryTagId integer, TrackingValue varchar)
Events(DiaryEventId integer PK AUTOINCREMENT, Type integer NOT NULL,
       Content varchar NOT NULL, Tag varchar, DiaryEntryId bigint NOT NULL)
Media(DiaryMediaId varchar(36) PK, Type integer NOT NULL, Data blob,
      Name varchar NOT NULL, FileEnding varchar NOT NULL,
      "Index" integer NOT NULL, DiaryEntryId bigint NOT NULL)
Tags(DiaryTagId integer PK AUTOINCREMENT, Value varchar NOT NULL,
     Type integer NOT NULL, Color varchar, Icon varchar)
Templates(TemplateId integer PK AUTOINCREMENT, Name varchar NOT NULL,
          Heading varchar NOT NULL, Text varchar NOT NULL)
```

### Observed cardinalities (this backup)

| Table | Rows | Notes |
|---|---|---|
| `Entries` | 1,393 | spans 2008-02-22 → 2026-06-12; 1,180 distinct days (multiple entries per day are supported) |
| `EntryTags` | 134 | `TrackingValue` is present in the schema but NULL on every row here |
| `Events` | 161 | all `Type = 0`; max 1 per entry |
| `Media` | 237 | attached to 190 entries, 1–6 per entry |
| `Tags` | 40 | 38 × `Type=0`, 2 × `Type=1` |
| `Templates` | 4 | HTML bodies, e.g. bullet-prompt templates |

## 3. Key encodings

### 3.1 `DiaryEntryId` = .NET `DateTime.Ticks` (the date *is* the primary key)

Entry IDs such as `633392789049243765` are 100-nanosecond intervals since
`0001-01-01`, i.e. .NET ticks:

```
datetime(1,1,1) + timedelta(microseconds=ticks / 10)
633392789049243765 → 2008-02-22 12:08:24.924
639168988157098265 → 2026-06-12 22:06:55.709
```

Unix-epoch offset: `621355968000000000` ticks. Consequences:

- There is **no separate date/time column** — deleting or re-dating an entry
  is a primary-key rewrite.
- Ticks are written as **local wall-clock time**, not UTC: there is no
  timezone column and the values align with the diary owner's local calendar
  days. Tooling that converts ticks via "as-UTC" then formats the date gets
  the correct calendar day; tooling that converts to a *tz-aware* local
  datetime from UTC would shift days.
- Because ticks encode time-of-day, several entries can share a calendar day.

### 3.2 `Entries.Text` and `Heading` are HTML

Rich text is stored as HTML fragments: `<p>`, `<br>`, `<strong>`, inline
emoji. 1,377 of 1,393 entries contain `<p>`; the rest are effectively empty
(`<p></p>`-style). Sizes: min 7 B, max ~156 KB, mean ~308 B. 85 entries have
an empty heading. 21 entries have effectively empty text — of these, only 2
carry media (photo-only entries are rare in this backup).

### 3.3 `Rating` is a 0–5 scale (0 = unrated)

Observed distribution: 0→1324, 1→1, 3→5, 4→3, 5→60. Value 2 simply never
occurs here; whether Diarium's UI allows values above 5 is **not observable
from this file** (the column is a plain integer).

### 3.4 `Media`: raw file bytes in blobs

`Media.Data` holds unencrypted, standard file bytes — verified magic numbers:

| `Type` | Endings seen | Magic | Meaning |
|---|---|---|---|
| 0 | `.jpg` | `FFD8FF … JFIF` | image |
| 1 | `.mp3` (`ID3`), `.m4a` (`ftyp`) | audio |
| 3 | `.pdf` | `%PDF-1.7` | document |
| 4 | `.mp4` | `ftyp` | video |

`Type=2` was not exercised by this backup (lifelogr's importer maps it to
"document" as a fallback). `Name` is a base name without extension — either a
share-in artifact name (`sharedContent`) or a timestamp-like generated name;
`FileEnding` carries the dot (`.jpg`). `"Index"` (0-based) orders multiple
media within one entry. `DiaryMediaId` is a 36-char GUID string.

### 3.5 `Events`: typed per-entry events, weather in practice

Every event here is `Type = 0` with a plain-text `Content` of the form
`"84 / 74 °F"` (temperature range), and a non-null `Tag` (9 distinct values,
4–17 chars — condition/category label). Diarium's event system supports more
event types (exercise, sleep, custom trackers) but none appear in this
backup, so the full `Events.Type` enum is **unknown**; treat `Type=0` as
weather and everything else as unverified.

### 3.6 `Tags.Type` distinguishes tag kinds

Observed: `0` = normal tag (38), `1` = person (2; each used in exactly 2
`EntryTags` rows). The importer's third kind, `2` = tracker (boolean check-off
items whose per-entry state lives in `EntryTags.TrackingValue`), is
**unobserved** here — `TrackingValue` is NULL on all 134 rows and no `Type=2`
tags exist. `Color`/`Icon` are NULL on all rows in this backup.

## 4. What Diarium backups carry that the schema doesn't show

- **No settings, no entry dates beyond the PK, no folder/notebook concept** —
  a `.diary` backup is a single flat journal.
- **Templates** are just reusable HTML bodies; they contain no user data.
- **`sqlite_sequence`** tracks `Tags`/`Events`/`Templates` autoincrement
  state — importing rows while preserving IDs must account for it.

## 5. Cross-check against lifelogr's importer

`backend/app/services/importers/diarium.py` was compared against the observed
file. Verification status:

| Importer assumption | Status |
|---|---|
| `DiaryEntryId` = .NET ticks (offset `621355968000000000`) | ✅ confirmed |
| `Text`/`Heading` are HTML needing tag-stripping | ✅ confirmed |
| `Rating` maps 1–5 → awful/bad/meh/good/great | ✅ consistent (0 = unrated skipped) |
| `Tags.Type` 0 = tag, 1 = person, 2 = tracker (skipped) | ✅ 0 and 1 confirmed; 2 unobserved, filter is harmless |
| `Media.Type` {0: image, 1: audio, 3: document, 4: video} | ✅ confirmed by magic bytes; `2` unobserved |
| Media blobs are raw bytes | ✅ confirmed |
| `"Index"` orders media | ✅ consistent (0–5 observed) |
| Old files may lack `Tags.Type` (guard via `PRAGMA table_info`) | ✅ defensive, untestable here |

One nuance worth knowing (not a bug): the importer treats ticks as UTC and
formats only the calendar date. Since Diarium stores *local* wall-clock in
the ticks, the resulting date is correct for same-day imports but would
mis-date entries if the importer ever emitted full timestamps in UTC.

## 6. Vendor corroboration (diariumapp.com + official FAQ forum, probed 2026-10-25)

Sources: the product page (`https://diariumapp.com/en`) and the official FAQ
(Flarum forum, `forum.diariumapp.com` discussions 3270 → 14 "General",
13 "Sync"; author *timo*, the developer). Vendor claims, not file evidence,
unless noted:

- **`.diary` is the official backup interchange format.** The site's feature
  list shows only human-readable exports (.docx/.txt/.html/JSON), but the
  FAQ confirms the "Backup diary" setting produces a `.diary` file and
  "Import diary" reads it back on a new device (d/13, "How does the sync
  work?"). That is exactly the artifact analyzed in this report. The JSON
  export matches lifelogr's second import path (`parse_diarium_json_entry`,
  capitalized `DiaryEntryId` keys).
- **Correction to an earlier inference: the *cloud-sync* payload is NOT the
  raw database.** The FAQ states sync data is "compressed and encrypted"
  (d/13), so the `Applications/Diarium` (OneDrive), `Apps/Diarium`
  (Dropbox) / `Diarium` (Drive, WebDAV) files cannot be opened externally.
  The unencrypted SQLite store applies to **local storage and `.diary`
  backups only** — which is what lifelogr imports, so no impact there.
- **Local-only by default.** Data stays on-device unless Cloud Sync is
  enabled; the developer keeps no server copies (d/14, "Where is the data
  stored?").
- **Protection is password/PIN/biometric at the app level** — no claim of
  file encryption, consistent with the observed unencrypted database.
- **Weather events come from Apple Weather and require an entry location**
  (d/14). This explains the sparsity of `Events` in the analyzed backup
  (161 weather events vs. 930 entries carrying coordinates): entries without
  a location never get weather. Sunrise/sunset follows the same rule.
- **Integrations enumerate plausible `Events.Type` values**: weather,
  camera roll, system calendar, word count, WorkingHours, Facebook, GitHub,
  Untappd, Last.fm, Trakt, "days of the year", Microsoft To Do, Strava,
  Apple Health / Health Connect, Google Timeline, sunrise & sunset, lunar
  phases. This is an *inferred candidate list* for the event enum — the
  numeric mapping beyond `Type=0` (weather, observed) remains unverified.
  (Camera-roll and calendar photos/events show *live* in the entry view and
  are not persisted as `Media`/`Events` rows unless attached — so the
  `Events.Type` enum likely covers only weather, sunrise/sunset, and the
  feed-style integrations.)
- **"Use tags to track your mood, weight or other metrics"** corroborates
  `Tags.Type=2` = tracker with per-entry `EntryTags.TrackingValue` (still
  unobserved in the analyzed backup).
- **"Create multiple entries per day or separate a single entry using
  timestamps"** corroborates the ticks-as-primary-key design (d/14 also
  documents the per-platform multiple-entries-per-day gesture).
- **"Unlimited attachments … or files of any other format"** corroborates
  the generic `Media.Name`/`FileEnding`/`Data` triple (any file type).
- **Migration sources** (d/14): Day One, Diaro, Journey, Memorize, Daylio,
  Diarly, Daybook (site adds Evernote and Apple Journal) — relevant context
  for lifelogr's own import coverage.
- **Minimum OS**: Windows 10 build 19041, Android 9, iOS 17.4, macOS 14.4;
  no older versions offered — bounds how far back schema/version support
  needs to go.

## 7. Limitations & unknowns

- Single-backup evidence: `Events.Type` enum beyond 0, `Tags.Type=2`
  trackers, `Media.Type=2`, rating values >5, and `Color`/`Icon` usage are
  all **unverified** by this artifact.
- The `user_version` upgrade path (1→4) is unknown; very old backups may lack
  columns the importer assumes (`Tags.Type` is already guarded).
- No REA tools were used; all conclusions above are from direct SQLite
  inspection and are reproducible from the SHA-256'd artifact.
