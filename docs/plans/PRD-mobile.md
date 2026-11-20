# PRD — LifeLogr Mobile

**Status:** Draft · 2026-11-20
**Owner:** Meeran
**Target product:** LifeLogr for Android and iOS

---

## 1. Summary

LifeLogr is a privacy-first, local-first journaling + notes app that today ships as a
Tauri desktop app and a browser web app on Linux, with a Python/FastAPI backend bound
to `127.0.0.1`. This PRD defines a **mobile version** whose core promise is the same:
your journal lives on *your* hardware, encrypted at rest, with no cloud in the
critical path.

Mobile is where journaling actually happens — capture in the moment, voice notes on
the go, photos, quick thought-dumps. Desktop remains the "heavy" surface (import,
backup, OCR bulk work, AI tooling); mobile is the **capture and read** surface that
keeps those two in sync.

---

## 2. Background & the central constraint

### 2.1 What exists today

| Layer | Today |
|---|---|
| Frontend | Vue 3 SPA · Vite · TypeScript · Pinia · Tailwind v4 |
| Backend | Python 3.11+ · FastAPI · SQLAlchemy 2.x · SQLite (WAL + FTS5) |
| Desktop shell | Tauri v2, spawns a **PyInstaller sidecar** backend on `127.0.0.1:18765` |
| Data | All on disk; per-item AES-256-GCM; optional encrypted cloud backup |
| AI | Ollama local by default; optional OpenAI-compatible cloud |
| Sync | **None.** There is exactly one data directory per machine. |

### 2.2 The one hard problem

> **The Python backend cannot ship on a phone.**

- **iOS:** no supported way to embed CPython + SQLite + a compiled service as a
  background sidecar in an App Store app.
- **Android:** possible in principle (Chaquopy / bundled interpreters) but the
  PyInstaller sidecar model does not transfer, and shipping a local HTTP server as
  an app architecture fights both OS sandboxes and battery life.

Meanwhile Tauri v2 **does** support iOS/Android for the *shell*, and the Vue SPA is
largely reusable. So the frontend story is easy and the backend story is the whole
project. Every decision below flows from that.

### 2.3 Non-negotiable principles (carried over from AGENTS.md)

1. **Local-first.** The phone must be fully usable offline; sync is a background
   concern, never a blocker for read or write.
2. **Private by default.** No telemetry, no third-party analytics, no cloud relay
   unless the user explicitly opts in and it is end-to-end encrypted.
3. **Single user.** No accounts, no multi-tenant anything. "Auth" = device pairing
   with the desktop, or a local passcode/biometric gate.
4. **Data is sacred.** Media files are never unlinked before the DB commit succeeds;
   deletes are restorable trash; exports are lossless. The same rules apply on
   mobile and in sync.

---

## 3. Goals

- **G1** — Capture-first mobile app: new entry in ≤ 2 taps from app open; voice
  recording, photos, and video clips attach inline.
- **G2** — Read and search everything on the phone, offline, including media
  (thumbnails) and attachments.
- **G3** — Desktop and phone converge automatically when both are reachable, with
  end-to-end encryption so the transport never sees plaintext.
- **G4** — Reminders fire on the phone via OS notifications (the APScheduler story
  does not translate; this is a re-implementation, see §7.4).
- **G5** — Ship Android first, iOS second (see §6.1), from one codebase.

## 4. Non-goals (v1)

- **N1** — No AI assistant on mobile v1. Ollama cannot run on-device meaningfully
  and piping journal text to a cloud provider violates the privacy default.
  (Revisit as an opt-in cloud-provider toggle post-v1.)
- **N2** — No OCR on-device in v1 (Tesseract on mobile is heavy); OCR stays a
  desktop-service behavior. Photos taken on mobile are OCRed when they reach the
  desktop, or later via a pluggable on-device OCR milestone.
- **N3** — No Edge TTS read-aloud on mobile v1 (network dependency); use the OS
  speech engine instead, stretch goal.
- **N4** — No direct cloud-backup management from mobile (Drive/OneDrive/Dropbox/
  Box/WebDAV OAuth flows stay desktop-only in v1). Mobile contributes to the
  desktop's backup by syncing to it.
- **N5** — No multi-device topologies (phone + phone + desktop) in v1: exactly one
  phone paired to one desktop instance.

---

## 5. Architecture decision

### 5.1 Options considered

| Option | Description | Verdict |
|---|---|---|
| **A. Thin client over network** | Phone app is a remote view onto the desktop backend (LAN/Tailscale/relay). No local store. | Rejected as primary: useless offline, violates local-first. |
| **B. Port the Python backend to mobile** | Chaquopy on Android; dead end on iOS. | Rejected: two divergent backends, iOS impossible. |
| **C. Rewrite backend in Rust, embed everywhere** | One Rust core used by the Tauri sidecar *and* linked into mobile; SQLite everywhere. | Correct end-state, but a multi-quarter rewrite; cannot be v1. |
| **D. Mobile-native store + E2E-encrypted sync to desktop** | Mobile app owns a real local database (SQLite) and replicates with the desktop over an encrypted channel using the existing REST shapes. | ✅ **Recommended.** Local-first holds; no Python on phone; reuses the Vue SPA. |

### 5.2 Recommended architecture (Option D)

```
┌─────────────── Phone ───────────────┐        ┌──────── Desktop ────────┐
│ Tauri v2 mobile shell               │        │ Tauri v2 desktop        │
│  └─ Vue SPA (shared codebase,       │        │  └─ Vue SPA (existing)  │
│      mobile layout profile)         │        │                         │
│ Local store: SQLite (WAL, FTS5)     │◄──────►│ FastAPI backend         │
│ Per-item AES-256-GCM (same scheme)  │  sync  │ (source of truth today) │
│ Capture queue (writes never block)  │  E2E   │ 127.0.0.1:18765         │
└─────────────────────────────────────┘  Enc   └─────────────────────────┘
```

- **Shell:** Tauri v2 mobile target, reusing `frontend/` with a mobile layout
  profile (bottom tab bar, sheet-based editors, thumb-reach nav). The existing
  `__TAURI_INTERNALS__` runtime detection in `frontend/src/api/client.ts` gains a
  third runtime: `mobile`, which talks to the **on-device store adapter** instead of
  an HTTP base URL.
- **Store adapter:** a TypeScript interface mirroring today's API layer
  (`src/api/`), implemented on-device. This is the key reuse lever: components and
  Pinia stores are written against the API layer already, so mobile swaps the
  transport, not the UI.
- **Sync engine:** incremental pull/push of entries, notes, tags, media, voice
  recordings, and folders against new sync endpoints on the desktop backend
  (`/api/v1/sync/*`), using updated-at + tombstones (soft delete already exists —
  trash becomes the tombstone source). Payloads are encrypted end-to-end with a key
  derived from the pairing secret (§7.6), so any transport works: LAN, Tailscale,
  or later an opt-in relay.
- **Conflict policy:** last-writer-wins **per field group** for edits (title/body/
  tags), create-wins for items; merges never destroy data — a conflicting edit on
  both sides keeps both bodies in a merge marker the user can resolve, in the spirit
  of the existing "merge same-day entries" feature.

### 5.3 Explicitly deferred

The Rust-core unification (Option C) is the long-term destination once sync semantics
are proven; v1's TypeScript store adapter and the desktop's `/sync` endpoints are
designed so the core can be swapped under them later.

---

## 6. Platforms & distribution

### 6.1 Order

1. **Android first** — larger share of the privacy-conscious/self-hosting audience,
   side-loadable (no store review gates for early builds), FCM-free notifications
   are feasible.
2. **iOS second** — requires Apple Developer account, store review, and the
   iOS-specific constraints in §9 (background limits, file system).

### 6.2 Distribution

- Android: direct APK/AAB from GitHub Releases (matching the existing
  `.deb`/AppImage release flow in `.github/workflows/build.yml`), then Play Store.
- iOS: TestFlight for early access, then App Store.
- No accounts, no license servers, no crash-reporting SDKs.

---

## 7. Functional requirements

Priority: **P0** = launch blocker, **P1** = fast-follow, **P2** = later.

### 7.1 Journal (P0)

- FR-1 List view of entries, chronological, with date grouping and tag chips.
- FR-2 Rich markdown editor (reuse existing editor components; mobile keyboard
  toolbar for bold/italic/heading/list instead of hotkeys).
- FR-3 Create/edit/delete entry; delete goes to the same restorable trash model.
- FR-4 Attach photo (camera or library) and video clip to an entry.
- FR-5 Record voice memo in-app; waveform/record-stop-replay parity with desktop.
- FR-6 Tag editor as a chip row (desktop parity — explicit `tag_ids` on save).
- FR-7 Favorites/pinned entries.
- FR-8 Entry detail with media gallery; images load via `/thumb`-equivalent
  thumbnails, full images on demand (**memory discipline: the OOM history of the
  WebKit renderer applies double on mobile** — thumbnails by default, streaming
  transfers, no unbounded galleries).

### 7.2 Notes (P0/P1)

- FR-9 (P0) Read/browse notes and folders; `#hashtag` tags-in-text convention and
  inline `#` autocomplete on edit (parity with `useInlineTags`).
- FR-10 (P1) Create/edit notes, including tabbed pages within a note.
- FR-11 (P1) Folder nesting create/move with the acyclic guard enforced client-side
  too.

### 7.3 Search (P0)

- FR-12 Full-text search over entries and notes on-device (SQLite FTS5 in the
  mobile store).
- FR-13 Semantic search **P2**: on-device embeddings are a stretch goal; v1 search
  is FTS-only. Semantic results from the desktop may be surfaced when connected
  (clearly labeled as requiring the desktop).

### 7.4 Reminders & notifications (P0)

- FR-14 Create/edit/delete reminders with cron-style scheduling, mirroring
  `ReminderService` semantics.
- FR-15 Local OS notifications at reminder time (Android: AlarmManager/WorkManager;
  iOS: UNUserNotificationCenter). The APScheduler reconciliation model translates
  to: **the mobile store is the source of truth on the phone, and notifications are
  re-registered from it on every app start and after every CRUD op** — the same
  contract as `SchedulerService.sync_reminders()`.
- FR-16 Catch-up: notifications missed while the app was killed fire on next launch
  (parity with `schedule_catchup`).

### 7.5 Sync (P0)

- FR-17 Pairing flow: desktop shows a pairing code/QR; phone scans; both derive a
  symmetric key (PAKE-derived; see §7.6).
- FR-18 Automatic background sync when the desktop is reachable; manual "Sync now"
  with last-synced timestamp and per-entity counts.
- FR-19 Sync covers: entries, tags, entry_tags, notes, note folders, note pages,
  media metadata + blobs, voice recordings, reminders. Settings and AI/backup
  config stay desktop-local.
- FR-20 Media transfer is incremental and thumbnail-first (only fetch full blobs on
  demand), with resumable chunked transfer for large files.
- FR-21 Tombstone-based deletion: soft-deleted items propagate as trash; permanent
  purge on desktop propagates as a true delete with file cleanup on the phone
  after the local DB commit (data-safety rule from AGENTS.md).
- FR-22 Conflict handling per §5.2; every auto-merge is visible and reversible
  from a "Sync activity" screen.

### 7.6 Security (P0 — this is the product)

- FR-23 Pairing uses a PAKE (e.g. SPAKE2) over the QR/short-code so the pairing
  secret never crosses the wire.
- FR-24 All sync traffic is end-to-end encrypted (AEAD, key from pairing secret);
  transport TLS is defense-in-depth, not the privacy boundary. Any future relay is
  blind by construction.
- FR-25 Per-item AES-256-GCM at rest on the phone, same scheme and key-stretching
  parameters as the desktop so synced ciphertext semantics match.
- FR-26 App lock: biometric (Platform authenticator) or passcode gate; auto-lock on
  background.
- FR-27 Data at rest lives in the app-sandboxed directory; on iOS additionally
  leverage Data Protection class `Complete`. Backups of the app include the DB
  only in encrypted device backups.
- FR-28 Desktop pairing is revocable (device list in desktop settings; revocation
  invalidates the session key immediately).
- FR-29 Zero third-party network calls. Every outbound request is to the paired
  desktop or an explicitly user-configured endpoint. A debug "network log" screen
  makes this auditable.

### 7.7 Capture ergonomics (P0 differentiators)

- FR-30 Home-screen/quick-capture: share-sheet target and a lock-screen-adjacent
  widget/action that opens a new entry composer directly.
- FR-31 Draft autosave: an unsent thought is never lost, even on app kill
  (write-through to local store on every keystroke debounce).
- FR-32 Voice capture from the composer in one tap; recording survives screen lock
  (foreground service on Android).

### 7.8 Settings & misc (P1)

- FR-33 Theme (light/dark/system), font size, markdown preview toggle.
- FR-34 Data stats (entry/note/media counts, storage used), "wipe this device"
  (destroys local copy only — desktop data untouched).
- FR-35 Import/export on mobile is **out** (N/A desktop-only); export button
  deep-links the user to the desktop flow.

---

## 8. UX direction

- **Layout profile, not a fork.** The SPA gains a `mobile` runtime profile:
  bottom tab bar (Journal · Notes · Search · Reminders · Settings), full-screen
  sheets for editors, swipe-back navigation. All of it behind the same routes and
  stores the desktop uses, so features stay in one codebase.
- **Composer-first.** The default tab opens into the timeline with a floating
  compose button; two taps from cold start to writing (FR-30 paths make it one).
- **Offline honesty.** Sync state is visible but quiet: a subtle status dot, never a
  blocking spinner. Nothing in the write path ever waits on the network.

---

## 9. Platform constraints & mitigations

| Constraint | Mitigation |
|---|---|
| iOS: no true background execution for sync | Sync on app open/foreground, on significant location/metered triggers where allowed, and via Background Tasks API opportunistic runs. Writes are always local-first, so missed sync windows lose nothing. |
| Android: background limits & battery (Doze) | WorkManager for sync; foreground service only during voice capture. |
| FCM-free notifications | Android: exact alarms (`AlarmManager`, `SCHEDULE_EXACT_ALARM` permission) with WorkManager fallback. iOS: local notifications (fine for time-based reminders; silent-push only exists if a relay is ever opted into — out of scope v1). |
| SQLite FTS5 on mobile | Ship a SQLite build with FTS5 enabled in the app bundle (the desktop already solved the qualified-column bug via `pysqlite3`; on mobile, bundle a known-good SQLite). |
| Media storage pressure on phones | Thumbnails-on-demand (FR-8, FR-20); user-visible storage meter (FR-34); per-device "keep full media" toggle, default on for last 90 days. |
| Tauri v2 mobile maturity | Tauri mobile is newer than desktop; pin versions, keep native-plugin surface minimal (camera, mic, notifications, biometrics), and keep all business logic in shared TS so a shell swap is survivable. |

---

## 10. Milestones

| Milestone | Scope | Exit criteria |
|---|---|---|
| **M0 — Spike (2–3 wks)** | Tauri v2 Android shell running the SPA with a fake in-memory store adapter; camera + mic plugins proven; SQLite-with-FTS5 embedded on device. | A demo entry with a photo can be created, killed, relaunched, and read on a real Android phone. |
| **M1 — On-device core (P0 UI)** | Real SQLite store adapter; journal CRUD, tags, media, voice; search; app lock. Still no sync. | All FR-1…8, 12, 26 pass on-device; app is genuinely usable offline. |
| **M2 — Sync alpha** | `/api/v1/sync/*` endpoints on desktop; PAKE pairing; encrypted pull/push; tombstones; media chunking. | FR-17…25, 28 pass; kill-and-resume sync with a 500-entry, 1GB-media journal completes without loss or duplication. |
| **M3 — Reminders + capture polish** | Local notifications, catch-up, quick-capture, share sheet, drafts. | FR-14…16, 30…32 pass; reminder fires with app killed (Android) and after relaunch (iOS catch-up). |
| **M4 — Android beta** | Public beta APK, crash-free instrumentation via **local logs only**, sync-activity UI. | 2 weeks of daily-driver use by the owner with zero data loss; crash-free sessions ≥ 99%. |
| **M5 — iOS** | TestFlight build; iOS background/notification constraints validated; App Store submission. | FR parity review (mobile-vs-android checklist) signed off; store approval. |
| **M6 — Fast follows (P1)** | Notes editing (FR-10…11), theme/settings (FR-33…34), sync polish. | — |

---

## 11. Success metrics

- **Adoption (personal):** the owner's daily capture moves majority-mobile within a
  month of M4 (measured locally via entry-source counts — no telemetry leaves the
  device; "metrics" here are inspectable in a local stats screen, FR-34).
- **Reliability:** zero data-loss incidents across sync (conflicts surface as
  resolvable merge markers, never silent overwrites); sync of the real production
  journal (the `com.lifelogr.desktop` data dir) round-trips byte-identical media.
- **Performance:** cold start < 2s on a mid-range Android phone; entry list scroll
  at 60fps with thumbnails; search over 10k entries < 300ms.
- **Privacy audit:** the §7.6 network-log screen shows zero unexpected hosts over a
  two-week usage window.

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Tauri v2 mobile gaps (plugins, webview quirks) | Medium | High | M0 spike gates everything; fallback is Capacitor wrapping the same SPA (store adapter makes this cheap). |
| Sync conflicts corrupt/lose journal text | Low | **Critical** | Field-group LWW + merge markers (FR-22); adversarial test: simultaneous edits on desktop and phone for every entity type in M2 exit criteria. |
| Schema drift between desktop DB and mobile store | Medium | High | Mobile store is created from a shared schema definition; the desktop's inline `_migrate_schema` list gains a mobile counterpart in the same file/PR — never a second source of truth. |
| Media sync bloats phone storage | Medium | Medium | Thumbnail-first + retention toggle (§9). |
| Apple review friction for a "local server pairing" app | Low–Med | Medium | The phone never runs a server; it is a client with E2E encryption — a well-trodden review category. |
| Scope creep into "rewrite in Rust" mid-stream | Medium | High | §5.3 explicitly defers it; sync API is the boundary. |

---

## 13. Open questions

1. **Sync transport in v1:** LAN-only + Tailscale documentation, or invest in an
   opt-in encrypted relay now? (Recommendation: LAN/Tailscale at M2; relay as its
   own PRD post-v1 — the E2E design must not depend on it.)
2. **Voice transcription:** desktop has voice recordings but transcription is not
   currently a core flow — should mobile get on-device speech-to-text for voice
   memos (whisper.cpp is viable on both platforms)? Strong capture differentiator;
   propose as P1 fast-follow.
3. **Widgets depth:** Android lock-screen/widget capture in M3 — how far (quick text
   only, or voice too)?
4. **Multiple desktops:** is one-phone-one-desktop (N5) acceptable through v1, or do
   users immediately want phone + two machines? Affects tombstone/anchor design in
   M2 — decide before M2, cheap to keep the door open.

---

## 14. Immediate next steps

1. Approve/annotate this PRD (especially §5 architecture, §7.6 security contract,
   and the one-phone-one-desktop assumption in §13.4).
2. Time-box the **M0 spike**: Tauri v2 Android target + store adapter + bundled
   FTS5 SQLite on a real device.
3. Draft the `/api/v1/sync/*` contract (endpoints, tombstone format, chunked media
   transfer) as a design doc in `docs/plans/` — it is the piece desktop-side work
   can start on independently of the mobile shell.
