# LifeLogr Enhancement Ideas from Diarium

**Date:** 2026-10-25
**Companion to:** [`diarium-format-analysis.md`](diarium-format-analysis.md)
(artifacts analyzed: a real `.diary` backup, diariumapp.com, and the official
FAQ forum). Each item cites where the idea comes from and what lifelogr
already has, so effort can be judged before picking anything up.

---

## Tier 1 — data you already accept but discard or hide

The Diarium importer (`backend/app/services/importers/diarium.py`) already
parses these out of the file; the app just doesn't do anything with them yet.

### 1. Map view for geotagged entries
`Entries.Latitude/Longitude` are imported into the entries model, and the
analysis found 930 of 1,393 entries carry coordinates — but no frontend code
references them. A map view (calendar-free, like Diarium's: pins per entry,
cluster by place/country, click → entry) would make ~two-thirds of a typical
imported journal visible in a way text search can't. Local-first friendly:
tile server can be self-hosted or cached (opt-in network).

### 2. Import Events (weather) instead of dropping them
The importer skips the `Events` table entirely. Weather is the one event type
verified in real files (`Type=0`, content like `"84 / 74 °F"`, condition in
`Events.Tag`). Importing them as per-entry context would enrich both the
entry view and future mood-vs-weather analysis. Verified mapping: only
`Type=0` is safe to map today; treat others as opaque.

### 3. Tag trackers with per-entry values
`Tags.Type=2` + `EntryTags.TrackingValue` encode Diarium's "track mood,
weight, or other metrics" feature (vendor-corroborated; not present in the
analyzed backup). Importing these as numeric/boolean trackers and charting
them over time would be a differentiating feature — lifelogr's mood is a
single 1–5 field; Diarium's model is n-trackers-per-entry.

### 4. "On this day"
Diarium's most-loved retention feature (page + daily notification). All data
needed is already in lifelogr's DB — it's purely a query + view + scheduled
notification (reminders infra already exists). Natural fit for the daily
writing prompt: show the prompt alongside entries from this day in past
years.

## Tier 2 — views & insights around the existing store

### 5. ~~Calendar and timeline views~~ — already present (correction)
lifelogr ships both: `/calendar` (CalendarGrid, the default route) and
`/timeline` (TimelineView), plus a media timeline. No work needed; when
implementing the Tier-1 items, just verify the calendar cell handles the
multi-entries-per-day case the importer already supports.

### 6. Journaling statistics
Diarium ships "statistics for your journaling habits": streaks, word counts,
entries-per-week, mood distribution. lifelogr has all the raw material (FTS5
bodies, moods, tags, media counts) and an AI backend that could narrate them.
Cheap to build, high perceived value.

### 7. Daily word-count goal
Part of Diarium's integrations ("track your entry's word count and work
towards your daily goal"). Trivial on top of #6; pairs with the existing
daily prompt/reminder loop.

### 8. Weather auto-fill for geotagged entries
Beyond importing past weather (#2): for entries written today with
coordinates, fetch current conditions — opt-in, since it's the one feature
that would make a network call tied to location data. Diarium uses Apple
Weather; an Open-Meteo (no API key, no account) endpoint fits lifelogr's
privacy posture better.

## Tier 3 — ecosystem breadth

### 9. More migration importers
Diarium imports from Day One, Diaro, Journey, Memorize, Daylio, Diarly,
Daybook, Evernote, Apple Journal. lifelogr currently handles Diarium (SQLite
+ JSON) and its own archives. Day One's JSON export and Daylio's CSV are
documented, common formats — importing from Diarium's own sources makes
lifelogr the "final destination" app rather than a Diarium-specific escape
hatch.

### 10. Human-readable export formats
Diarium exports .docx/.txt/.html/JSON; lifelogr's export covers archive,
`.diary` (round-trip verified), and Markdown ZIP. Adding .docx/.html targets
non-technical users leaving either app — the format analysis documents the
mapping table needed.

### 11. Entry-page context sidebar (camera roll / calendar)
Diarium shows photos taken that day and calendar appointments *in the entry
composer* without persisting them (attach only on request). lifelogr could
list files from a user-chosen photos directory by date, plus read the local
system calendar (read-only ICS/`.local/share/evolution` on Linux). Same
opt-in privacy model as web-clip.

### 12. Feed integrations (GitHub, Last.fm, Trakt, MS To Do, Strava)
Diarium's Events concept generalizes to daily activity feeds. For lifelogr,
a "context feed" panel fed by public APIs (GitHub commits, Last.fm scrobbles)
would work and can cache locally like the TTS cache. Lower priority: more
OAuth surface, and these serve a narrower audience than Tier 1.

## Explicitly not recommended

- **Shared journals via a common cloud account** (Diarium supports two people
  syncing one journal): conflicts with lifelogr's single-user, no-auth,
  loopback-only security model.
- **Encrypted/proprietary cloud sync payload**: Diarium's sync files are
  compressed+encrypted and *unreadable* without the app (FAQ, d/13).
  lifelogr's plain SQLite-in-cloud backup is strictly better for data
  sovereignty — don't copy this.
- **Biometric/PIN app lock**: the backend is loopback-only behind a desktop
  shell; OS-level session security already covers this threat model.
