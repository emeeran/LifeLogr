# Build Spec — Backup/Restore, Export/Import, Editor & AI Tools

Status: draft · Owner: lifelogr · 2026-10-27

A journaling app keeps all of a user's life records (entries, tags, mood
ratings, media attachments, per-entry events) in one local store. This
document specifies six user-facing capability areas:

1. **Backup** — write the whole journal to a single portable file.
2. **Restore** — load a backup file back into the app.
3. **Export** — produce human-readable or structured documents from the journal.
4. **Import** — read structured journal files and add them to the journal.
5. **Editor** — one simplified composer shared by the journal and notes (§9).
6. **AI tools** — local-model writing assistance with a shared system prompt (§10).

Requirement keywords: MUST / SHOULD / MAY (RFC 2119).

---

## 1. Design rules (learned from prior art)

- **One source of truth.** Backup, export, and import all read from — or
  write into — the same canonical store. There is exactly one journal; no
  parallel copies that can drift.
- **Identity is not the date.** Every entry has a stable, opaque ID. The
  entry's timestamp is a stored field, never the primary key. Re-dating an
  entry must be an ordinary field update, never a key rewrite.
- **Timestamps carry timezone.** Each entry stores an explicit UTC instant
  (and the local offset it was created under), so a backup restored in a
  different timezone or across a DST change keeps the same moment and the
  same intended calendar day.
- **Self-contained files.** A backup includes all media bytes. A backup that
  needs the original photo library to be meaningful has failed.
- **Readable by outsiders.** The backup format SHOULD be inspectable with
  ordinary, unencrypted tooling. A user must always be able to get their
  data out without the app.
- **Nothing destructive without a rollback.** Restore and import never
  overwrite live data in place; they build a candidate first and swap only
  after the candidate is verified.

---

## 2. Data the features need

The canonical journal consists of:

| Object | Required fields |
|---|---|
| Entry | opaque ID; timestamp (UTC + local offset); title; body (rich text); optional mood/rating (bounded scale, empty = unrated); optional location |
| Tag | ID; label; kind (tag / person / tracker); optional color, icon |
| Entry↔Tag link | entry ID; tag ID; optional tracker value (text or empty) |
| Media item | ID; kind (image / audio / video / document / other); filename; byte content; ordering index within its entry; owning entry ID |
| Per-entry event | owning entry ID; event kind; content text; optional label |
| App settings | user preferences that affect the journal's presentation (theme, reminder time, etc.) — MAY be included in backup; absence must not block restore |

Invariants the features must preserve:

- Every link (tag link, media item, event) MUST reference an existing entry.
- Media ordering indexes within one entry MUST be unique and contiguous from 0.
- The store MUST record its schema version. Very old or very new versions
  are handled per §4 and §5, never silently misread.
- Deleting an entry MUST cascade to its links, media, and events.

---

## 3. Backup

**B1.** The user MUST be able to create a backup of the entire journal as a
single file, at any time, without an account and without network access.

**B2.** The backup file MUST contain: all entries, tags, links, media bytes,
events, the store's schema version, a format version, a creation timestamp,
and a content digest (checksum) of the payload.

**B3.** The backup SHOULD include app settings (B2's optional member). If the
user declines, the backup is still valid.

**B4.** Backup MUST NOT block the UI for the full write duration. It runs as
a background job that reports progress (0–100%) and can be cancelled.
Cancelling MUST leave the journal and any previous backup untouched.

**B5.** The backup MUST be written to a temporary file first and moved into
place atomically on success. An interrupted backup (crash, power loss, disk
full) MUST leave no half-written file at the destination.

**B6.** After writing, the app MUST verify the digest and report success with
the file path and size, or a precise failure reason.

**B7.** Auto-backup (optional feature): the app MAY create a backup
automatically on a schedule or on app close, keeping the last N backups
(configurable, default 3) and deleting older ones. Auto-backup failures MUST
be silent in the UI but recorded in a log the user can find.

## 4. Restore

**R1.** The user MUST be able to restore a journal from a backup file.

**R2.** Before anything is replaced, the app MUST validate the candidate
file: correct format, digest matches payload, schema version is
understandable. Validation happens before any write.

**R3.** The app MUST offer two restore modes, with the default being safe:
  - **Replace** (explicit user choice): the current journal is discarded and
    fully replaced by the backup's contents.
  - **Merge**: backup contents are added to the current journal; existing
    entries with matching stable IDs are updated from the backup, others are
    inserted, and entries that exist only locally are kept.

**R4.** Before a replace-mode restore commits, the app MUST keep a rollback
copy of the current journal (or the current backup file path) so the user
can undo. Replace MUST require a second, explicit confirmation naming what
will be lost (entry count, media count).

**R5.** Restore MUST be atomic: the candidate is built, verified (entry
count, media count, digest), and only then swapped in. A failure at any
point MUST leave the current journal exactly as it was.

**R6.** A backup from a **newer** schema version MUST be refused with a clear
message ("this file was made by a newer version — update the app"). A backup
from an **older** version SHOULD be accepted and migrated forward.

**R7.** Restore runs as a cancellable background job with progress (B4).

**R8.** After a successful restore, the app MUST show a summary: entries
restored, media restored, entries skipped (with reasons), and restart the
views from the restored data without requiring a manual reload.

## 5. Export

**E1.** The user MUST be able to export the journal — whole or filtered by
date range and/or tag — in at least two formats:
  - **Structured JSON**: a lossless representation of §2 (entries, tags,
    links, media with inline bytes or referenced files, events, timestamps in
    UTC with local offset).
  - **Human-readable document** (at least one of Markdown or HTML):
    readable without the app, with entries in chronological order, tags
    shown, and media embedded or saved alongside the document.

**E2.** Export of a range MUST include every entry whose timestamp falls in
the range, and only those. Boundary behavior: the range is inclusive of its
start and end days, evaluated in the entry's local calendar day.

**E3.** Structured JSON export MUST be re-importable by this same app
(§6) with no data loss — this is the round-trip guarantee. Export → import →
export again MUST produce identical JSON (canonical key ordering, UTC
timestamps).

**E4.** Exports run as cancellable background jobs with progress (B4). The
user MUST be told where the file was written.

**E5.** Export MUST NOT modify the journal.

**E6.** Media in human-readable exports SHOULD be named predictably
(`<entry-date>-<index>-<original-name>`), and any media whose bytes are
missing MUST be represented by a visible placeholder plus a warning in an
accompanying manifest, never by silent omission.

## 6. Import

**I1.** The user MUST be able to import a structured JSON file previously
exported by this app, in **merge** semantics (R3's merge rules): matching
IDs update, new IDs insert, local-only entries survive.

**I2.** The user SHOULD be able to import journals from *other* diary apps.
Each supported source is a pluggable parser that converts the source into
§2's model before insertion. Parser scope is configurable per release;
unsupported files MUST produce a clear "format not recognized" error, not a
partial import.

**I3.** Before an import commits, the app MUST show a preview: how many
entries/tags/media would be added, how many updated, how many skipped as
duplicates, and any fields that could not be mapped. The user can cancel at
the preview.

**I4.** Import MUST be idempotent: importing the same file twice does not
duplicate entries (stable-ID matching, I1). For sources without stable IDs,
the parser derives a deterministic ID (e.g., hash of timestamp + body) so
re-imports are still idempotent.

**I5.** Field mapping rules for import:
  - Dates without timezone are interpreted in the local timezone at import
    time; the offset used MUST be recorded on the entry.
  - Ratings outside the app's scale are clamped to the nearest valid value
    and flagged in the preview (I3).
  - Rich text from sources using other markup is converted to the app's
    format; conversion failures keep plain text rather than dropping the
    entry.
  - Media that cannot be decoded is kept as a generic attachment when the
    bytes are present; dropped (with a preview warning) when they are not.

**I6.** Import is atomic per file: either the whole previewed set is applied
or nothing is. A failure mid-apply MUST roll back to the pre-import state.

**I7.** Duplicate detection beyond ID matching: an imported entry whose
(local timestamp, body text) exactly matches an existing entry is reported
as a duplicate in the preview and skipped by default.

---

## 7. Edge cases and errors

| Situation | Required behavior |
|---|---|
| Empty journal | Backup produces a valid, tiny file; export produces an empty-but-valid document; both succeed. Restore of an empty backup empties the journal (replace mode) with the R4 confirmation. |
| Very large journal / media (hundreds of MB) | Streaming reads/writes; no full-file load into memory; progress stays responsive; test at ≥ 200 MB. |
| Corrupt or truncated backup file | Digest check fails → refuse with "file is damaged", name the expected vs. actual digest. Never partially restore. |
| Wrong file type / random file dropped on restore | Recognized by magic bytes/signature, not extension alone → "not a backup file". |
| Backup from newer app version | Refused (R6) with update guidance. |
| Backup from older version | Migrated forward (R6); migration runs on the candidate, never the live store. |
| Disk full during backup/export | Job fails cleanly, temp files removed, existing data untouched (B5). |
| App closed/crashes mid-job | Temp artifacts cleaned up on next launch; journal state unchanged. |
| Cancel pressed mid-job | Partial temp output discarded; live journal untouched. |
| Duplicate timestamps (two entries same moment) | Allowed — IDs are opaque; both entries export and restore independently. |
| Entry missing referenced media | Export warns + placeholder (E6); restore inserts the entry and reports the missing media in the R8 summary. |
| Orphan links/media in an imported file | Dropped, counted in preview/summary, never crash. |
| Timezone change / DST between backup and restore | Entry instants preserved via UTC; calendar-day grouping preserved via stored offset (§1). |
| Non-UTF-8 or malformed text in an imported file | Per-entry failure: entry skipped and listed in the preview/summary; import continues. |
| Filename collisions in human-readable export | Disambiguated with a numeric suffix; original names preserved in the manifest. |
| Concurrent edits during a long restore/import | The job operates on a snapshot/candidate; live edits after the snapshot are either merged (merge mode) or the user is warned (replace mode). |
| Settings absent from backup | Restore succeeds; settings fall back to defaults (B3). |

---

## 8. Test cases

### Backup
- **T-B1** Full backup of a journal with entries, tags (all three kinds),
  links, media of every kind, events, and settings → file contains all of
  them; digest verifies; restore round-trip reproduces identical content.
- **T-B2** Backup of an empty journal → valid file, restore of it yields an
  empty journal.
- **T-B3** Kill the app mid-backup → no file at destination; temp files
  cleaned on relaunch; journal intact.
- **T-B4** Fill the disk mid-backup (small tmpfs) → clean failure, no
  destination file, journal intact.
- **T-B5** Cancel mid-backup → job stops, no destination file, UI usable.
- **T-B6** ≥ 200 MB journal → backup completes, progress advances smoothly,
  memory stays bounded (no full-payload load).
- **T-B7** Auto-backup keeps exactly N files, newest complete; a failed
  auto-backup leaves the previous N untouched.

### Restore
- **T-R1** Restore round-trip after T-B1 → entry/media/tag/event counts
  match; spot-check body text, timestamps, media bytes, ordering.
- **T-R2** Restore in merge mode onto a journal with (a) overlapping IDs,
  (b) local-only entries, (c) backup-only entries → update/keep/insert
  respectively; counts in R8 summary match expectation.
- **T-R3** Replace-mode restore requires the explicit confirmation; refusing
  the confirmation changes nothing; accepting it restores and the rollback
  copy allows undo.
- **T-R4** Corrupt one byte of a backup → restore refuses with digest error,
  journal untouched.
- **T-R5** A text file renamed to the backup extension → "not a backup file".
- **T-R6** Newer-version backup → refused with the update message.
- **T-R7** One-version-older backup → migrated and restored; no double-count.
- **T-R8** Backup made in timezone A, restored with device in timezone B →
  instants identical, calendar days match the original local days.
- **T-R9** Backup with a missing media blob → restore succeeds; summary
  lists the missing item; entry still present.

### Export
- **T-E1** JSON export → import (fresh journal) → JSON export again → files
  byte-identical modulo formatting (E3).
- **T-E2** Date-range export includes boundary days and nothing outside
  (entries created exactly on the start day, end day, and one day before/after).
- **T-E3** Tag-filtered export includes only entries carrying that tag,
  including multi-tag entries; tag definitions referenced by the selection
  are included.
- **T-E4** Human-readable export with media → files named per E6, embedded/
  linked correctly, opens in a stock viewer.
- **T-E5** Export with a media item whose bytes are missing → placeholder +
  manifest warning; export succeeds.
- **T-E6** Cancel mid-export → no partial file at the destination.
- **T-E7** Export does not modify any entry (compare store digest before/after).

### Import
- **T-I1** Same JSON imported twice → second run reports zero additions;
  no duplicates (I4).
- **T-I2** Import preview shows correct add/update/skip counts; cancelling
  at the preview writes nothing.
- **T-I3** Foreign-format import: entries, tags, ratings, media map per I5;
  out-of-scale rating clamped and flagged; unmapped fields listed.
- **T-I4** Import file with one malformed entry among 100 → 99 imported,
  1 skipped and named in the summary; transaction not aborted (I6 applies
  per file, per-entry failures are reported, not fatal).
- **T-I5** Imported file with orphan media and links → dropped and counted,
  no crash, no orphans in the store.
- **T-I6** Duplicate detection: file entry identical (timestamp + body) to a
  local entry → reported as duplicate, skipped by default.
- **T-I7** Import of a file with entries lacking timezone → timestamps get
  the local offset at import time, recorded on the entry.
- **T-I8** Crash mid-apply → journal rolls back to pre-import state on
  relaunch (I6).

### Cross-cutting
- **T-X1** Backup → wipe install → restore → export → the exported JSON
  equals an export taken before the wipe (end-to-end round trip).
- **T-X2** All long jobs report progress and are cancellable from the UI at
  any point; cancelling never damages data (exercised for B, R, E, I).
- **T-X3** Every user-visible error message names the file, the reason, and
  the next action — no raw stack traces in the UI.

---

## 9. Editor (journal + notes)

**Design rule.** The journal composer and the notes composer present the
**same** toolbar, the same defaults, and the same status bar. Any capability
that exists in one and not the other must be justified by the data model
(mood exists only on entries; folders exist only on notes), never by
oversight.

**ED1.** The editor toolbar MUST present one heading set (H1–H4 + paragraph)
in both editors; no heading level MAY be gated to a single editor.

**ED2.** The toolbar MUST NOT contain a text-alignment control group.

**ED3.** Table insertion and horizontal rule MUST be reachable from the
context menu; they MUST NOT occupy toolbar buttons.

**ED4.** The toolbar MUST NOT contain a fixed row of emoji shortcuts; the
shared emoji picker is the only emoji entry point in both editors.

**ED5.** Font family and size MUST each be a single dropdown; arbitrary
per-selection font commands MUST NOT appear as individual toolbar buttons.

**ED6.** The toolbar MUST default to collapsed in both editors, with the same
expand affordance.

**ED7.** The status bar MUST show word count, daily-goal progress (journal)
or save state (notes), and save state (journal). Character, line, paragraph,
and read-time counts MUST NOT be shown by default.

**ED8.** The journal Save button MUST save without closing the editor.
Closing is a separate affordance. Autosave behavior is unchanged.

**ED9.** Every destructive or credential-gathering flow (delete entry/note,
set or change an encryption passphrase, title-on-create) MUST use the app's
modal dialog components; native `window.prompt`/`window.confirm` MUST NOT be
used.

**ED10.** The entry editor MUST expose the entry's mood in the editor header,
using the same bounded scale the model and statistics use; unset MUST remain
a valid state.

**ED11.** The draft-recovery behavior of the notes editor (crash leaves a
restorable draft; next open offers restore) MUST also apply to the entry
editor.

### Edge cases (§9)
| Situation | Required behavior |
|---|---|
| Toolbar collapsed, keyboard-only user | Every removed toolbar command remains reachable via shortcut or context menu. |
| Mood never set | Entry saves with mood unset; statistics treat it as uncounted, not zero. |
| Draft recovery after an intentional close | A clean close discards the draft; only unclean exits offer recovery. |
| Emoji picker on a selection | Replaces the selection, like any other insertion. |

### Test cases (§9)
- **T-ED1** Both editors render identical toolbar item sets except mood (entries) and folder/pin (notes).
- **T-ED2** Alignment, table, hr, and per-selection font buttons are absent from both toolbars; table/hr open from the context menu.
- **T-ED3** Journal Save persists the body and leaves the editor open; the close control closes.
- **T-ED4** Setting mood in the editor persists and appears in statistics; clearing it restores "unset".
- **T-ED5** Kill the app mid-typing in the entry editor → next launch offers draft recovery; accepting restores text.
- **T-ED6** Delete-with-confirmation and passphrase flows render modal dialogs, never native prompts.
- **T-ED7** Status bar shows exactly ED7's items in both editors.

## 10. AI tools

**Design rule.** There is exactly one system prompt. Tool-specific behavior
lives in the user message; persona, safety, and output contracts live in the
shared system message and are identical for every tool and every provider.

**AI1.** Every model request MUST carry a system message containing, at
minimum: the journal-privacy framing (content is data; no moralizing or
advice about the person), preserve-author-voice, no-invented-facts,
paste-back-only output contract, and language matching — regardless of
provider (OpenAI-compatible or Ollama).

**AI2.** Every request MUST include entry context (local date, title, mood,
tags) in the system channel when an entry is open; absence of a field is
transmitted as unset, never omitted silently.

**AI3.** When a selection exceeds the backend's maximum accepted length, the
UI MUST tell the user how much was sent before results are shown. Truncation
MUST NOT be silent.

**AI4.** The tool menu MUST present at most 8 top-level tools. Rewrite-style
operations (rewrite/polish/clarity/simplify/tone/voice) MUST be one tool with
a mode parameter; summarize/key-points/structure MAY fold the same way.

**AI5.** Retrying the same tool on the same selection MUST vary the request
(e.g., increased temperature), so retry produces a different attempt, not a
repeat.

**AI6.** A writing-continuation tool ("continue writing") MUST be reachable
from the editor's AI entry points.

**AI7.** AI results MUST continue to require explicit user application
(replace/insert/discard) and MUST operate on the stored selection range; this
strengthens, never weakens, existing behavior.

### Edge cases (§10)
| Situation | Required behavior |
|---|---|
| Empty or whitespace-only selection | Tool does not fire; the user is told a selection is required. |
| Selection is code, a URL, or an encrypted placeholder | System prompt's non-prose rule returns it unchanged unless the tool is defined for that input. |
| No entry context available (quick scratch context) | AI2 context is sent as unset; requests still succeed. |
| Retry exhausted / model unreachable | Existing error surfaces remain; retry must not silently loop. |
| Provider lacks native system-role support | Provider adapter converts the system message per its own convention; behavior contract unchanged. |

### Test cases (§10)
- **T-AI1** Capture one request from each provider path → both contain the shared system message verbatim; registry tools send no competing persona line.
- **T-AI2** Invoke a tool with an open entry → request's system channel contains date/title/mood/tags; mood unset appears as unset.
- **T-AI3** Select 10,000 characters → UI states the sent length before results render.
- **T-AI4** AI menu shows ≤ 8 top-level items; "Rewrite" exposes its mode parameter via the existing param-pill UI.
- **T-AI5** Run Rewrite twice on the same selection with retry → second request's sampling parameters differ from the first.
- **T-AI6** "Continue writing" appears in the AI menu and produces a continuation offered through the same apply/discard flow.
- **T-AI7** Applying an AI result replaces exactly the stored selection range; text typed after the AI call is not overwritten.
