# LifeLogr — Architecture & Developer Guide

> A living, code-level companion to the [User Manual](manual/USER_MANUAL.md) and
> [API Reference](manual/API_REFERENCE.md). This document explains **how LifeLogr is
> built and how to work in it**, not how to use it.
>
> *Version 0.7.1 · last updated 2026-07-27*

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [System Architecture](#2-system-architecture)
3. [Repository Layout](#3-repository-layout)
4. [Backend Deep-Dive](#4-backend-deep-dive)
5. [Frontend Deep-Dive](#5-frontend-deep-dive)
6. [Desktop (Tauri) Deep-Dive](#6-desktop-tauri-deep-dive)
7. [Data-Flow Walkthroughs](#7-data-flow-walkthroughs)
8. [Configuration, Secrets & Data Locations](#8-configuration-secrets--data-locations)
9. [Build, Release & CI Pipeline](#9-build-release--ci-pipeline)
10. [Testing Strategy](#10-testing-strategy)
11. [Extending LifeLogr (How-To)](#11-extending-lifelogr-how-to)
12. [Conventions & Gotchas](#12-conventions--gotchas)
13. [Common Development Tasks](#13-common-development-tasks)

---

## 1. Design Principles

LifeLogr is a **single-user, local-first journaling app for Linux**. Every architectural
decision flows from a small set of principles:

| Principle | What it means in practice |
|---|---|
| **Local-first** | The database, media, and AI all live on-device. The app is fully functional offline. |
| **Single-user, loopback-only** | The backend binds to `127.0.0.1` only. There is **no auth** — the trust boundary is the loopback interface, not a login system. (See ADR-002.) |
| **Privacy by default, cloud opt-in** | Nothing leaves the device unless the user explicitly enables a cloud AI provider or cloud backup. A live egress report makes this auditable. |
| **Self-healing on boot** | The packaged app must repair itself (schema, FTS index, scheduler jobs, backup config) without external tooling — so schema migrations are **inline and idempotent**, not Alembic. |
| **Two ships from one codebase** | A native **Tauri desktop** build and a **browser-served web** build share one backend and one frontend. The only real divergence is the screen-snippet (desktop-only) and how the backend is launched. |

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         LifeLogr (one user)                          │
│                                                                      │
│   ┌────────────────────┐        HTTP (127.0.0.1 only)               │
│   │  Frontend (Vue 3)  │ ───────────────────────────────┐            │
│   │  Vite · Pinia · TS │                                ▼            │
│   └─────────▲──────────┘                 ┌────────────────────────┐  │
│             │ webview / browser tab       │  Backend (FastAPI)     │  │
│   ┌─────────┴──────────┐                 │  async · SQLAlchemy 2  │  │
│   │  Tauri shell (Rust)│ sidecar spawn   │  SQLite WAL + FTS5     │  │
│   │  + screen snip     │ ──────────────▶ │  + embeddings          │  │
│   └────────────────────┘                 └───────────┬────────────┘  │
│                                                        │              │
│                          ┌────────────────────────────┼──────────┐   │
│                          ▼                            ▼          ▼   │
│                   <data-dir>/lifelogr.db        Ollama     Tesseract │
│                   <data-dir>/media/             (AI)       (OCR)     │
│                   <data-dir>/.secret_key        :11434     local     │
└──────────────────────────────────────────────────────────────────────┘
                                 │ (opt-in only)
              ┌──────────────────┼───────────────────────────┐
              ▼                               ▼               ▼
   Cloud AI (OpenAI-compat)        Cloud backup (OAuth)    Web-clip URL
   OpenAI / Groq / OpenRouter      Google Drive / OneDrive  (SSRF-hardened
   / Kimi / Gemini / Custom        / Dropbox / Box / WebDAV   fetch)
```

### Three runtimes, one codebase

| Runtime | Frontend served by | Backend launched by | Default data dir |
|---|---|---|---|
| **Desktop (Tauri)** | Tauri webview loads `frontend/dist` | Tauri spawns the PyInstaller sidecar `lifelogr-backend` (port **18765**) | `~/.local/share/com.lifelogr.desktop/` |
| **Web (`.deb`)** | Backend serves `frontend/dist` as static files | On-demand launcher picks a free port (prefers **18765** for OAuth), runs `uvicorn` as the desktop user | `~/.local/share/lifelogr/` |
| **Dev (from source)** | Vite dev server on `:5173` (proxies `/api` to backend) | `uv run uvicorn app.main:app --reload --port 8000` | `~/.local/share/lifelogr/` |

The frontend auto-detects which runtime it's in via `__TAURI_INTERNALS__`
(`frontend/src/api/client.ts`): in Tauri it talks to `http://127.0.0.1:18765`; in
dev/web it uses relative URLs (served/proxied by the same origin).

---

## 3. Repository Layout

```
diary/
├── backend/                 # FastAPI + SQLAlchemy + SQLite
│   ├── app/
│   │   ├── main.py          # App factory, lifespan, middleware, router mount
│   │   ├── core/            # config.py · database.py · security.py · cron_utils.py
│   │   ├── routers/         # one file per REST resource (+ _oauth_helpers.py)
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── schemas/         # Pydantic v2 request/response schemas
│   │   └── services/        # business logic (+ importers/ subpackage)
│   ├── tests/{unit,integration}/
│   ├── .env.example         # documented env defaults
│   └── pyproject.toml       # deps, ruff, mypy(strict), pytest, coverage gate
├── frontend/                # Vue 3 SPA
│   ├── src/
│   │   ├── api/             # shared fetch client + one module per domain
│   │   ├── stores/          # Pinia stores
│   │   ├── composables/     # reusable logic (incl. aiToolRegistry)
│   │   ├── components/      # feature-grouped SFCs (no views/ dir)
│   │   ├── utils/           # externalLink.ts, settings.ts, …
│   │   ├── router.ts · main.ts · App.vue · version.ts
│   ├── tests/               # Playwright e2e (*.spec.ts)
│   └── vitest.config.ts · playwright.config.ts
├── desktop/                 # Tauri v2 shell
│   ├── src-tauri/           # Cargo.toml · tauri.conf.json · src/main.rs
│   ├── scripts/pyinstaller.spec   # bundles the Python backend → lifelogr-backend
│   └── Makefile             # build-frontend / build-backend / build-sidecar / build
├── scripts/                 # build-web-deb.sh · check_version.py · …
├── docs/                    # this file + SDD artefacts + manual/
├── Makefile                 # top-level dev + SDD-pipeline targets
├── Dockerfile · docker-compose.yml   # optional containerized deployment
└── .github/workflows/       # ci.yml (gate) · build.yml (release artifacts)
```

---

## 4. Backend Deep-Dive

### 4.1 Bootstrap, lifespan & middleware (`app/main.py`)

The app is built via a FastAPI factory with an `async` **lifespan** context manager. On
**startup** it runs, in order:

1. Load persisted runtime settings (model picks, feature toggles).
2. `init_db()` — open the engine, run inline migrations, build FTS5.
3. Data-integrity checks (**warn-only** — never block boot).
4. Start the backup scheduler; schedule a reminder **catch-up** sweep ~30 s after boot.
5. Verify backup-system health (self-heals a missing `auto_backup` job).
6. A broad integrity battery (DB structure, FTS, encryption key).

On **shutdown** it stops the scheduler, cancels pending enrichment tasks, disposes the
DB engine, and closes the Ollama HTTP client.

**Middleware stack** (registered top-down):

| Middleware | Behaviour | Reference |
|---|---|---|
| **CORS** | Allows `settings.CORS_ORIGINS` (dev only). | `main.py` |
| **Request logging** | Tags each request with a UUID; logs elapsed time; skips noisy `/health` + static paths. | `main.py` |
| **Rate limiting** | In-memory token bucket, `60/min` default; **skipped unless `APP_ENV=production`** so the desktop app doesn't self-throttle its background enrichment. | `main.py` |
| **Origin/CSRF guard** | Rejects **mutating** requests whose `Origin` isn't loopback. | `main.py` |

**The `pysqlite3` swap** (top of `main.py`): in **frozen/PyInstaller** builds the stdlib
`sqlite3` is replaced by `pysqlite3` (a statically-linked modern SQLite). This fixes a
qualified-column bug in FTS5 (`entries.title`) that previously forced the packaged app
to **skip FTS entirely**. The swap only triggers when `sys.frozen` is set.

All routers mount under `/api/v1`; a catch-all serves the built SPA from
`frontend/dist/` when present (`index.html` no-cache, hashed assets immutable).

### 4.2 Configuration (`app/core/config.py`)

A Pydantic `BaseSettings` instance loaded from env / `.env`. Highlights:

| Setting | Default | Notes |
|---|---|---|
| `APP_VERSION` | `0.7.1` | Keep in sync via `make bump`. API source of truth. |
| `APP_ENV` | `development` | `production` enables rate limiting + disables `/docs`. |
| `SECRET_KEY` | `change-me-before-production` | AES key for encrypted credentials. **Must** be set for non-launcher runs. |
| `DATA_DIR` | platform default (`~/.local/share/lifelogr` on Linux) | Overridable — see §8. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` | `:11434` / `llama3.2:3b` / `nomic-embed-text` | Local AI defaults. |
| `RATE_LIMIT` | `60/minute` | Production only. |
| `MAX_MEDIA_SIZE_BYTES` | 25 MiB | Per-file upload cap. |
| `MAX_IMPORT_SIZE_BYTES` | 2 GiB | Backup-import cap. |

**`DATA_DIR` resolution** (highest → lowest priority):

1. `LIFELOGR_DATA_DIR` env var (legacy alias `DIARI_DATA_DIR` also honoured).
2. The **storage-override file** `$XDG_CONFIG_HOME/lifelogr/data-location.json`
   (`{"data_dir": "/abs/path"}`) — written by **Settings → Data → Storage location**.
   It lives *outside* `DATA_DIR` on purpose, so it survives a relocation.
3. Platform default.

### 4.3 Database (`app/core/database.py`)

- **Engine/session:** `create_async_engine` (`aiosqlite`); `expire_on_commit=False`.
- **Pragmas** (set via a `connect` event listener): `journal_mode=WAL`,
  `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=10000`,
  `auto_vacuum=INCREMENTAL`, 4 MiB cache, temp tables in memory. SQLite uses
  `pool_size=1` automatically.

#### Inline migrations (no Alembic)

Schema evolution is **idempotent and inline** — `_migrate_schema()` runs on every boot:

- `_COLUMN_MIGRATIONS` — `(table, column, ALTER TABLE … ADD COLUMN …)` tuples; each is
  checked against `PRAGMA table_info` and skipped if present.
- `_INDEX_MIGRATIONS` — `(index_name, CREATE INDEX IF NOT EXISTS …)` tuples.

> **To add a column or index:** append a tuple to the relevant list in
> `database.py`. Do **not** reintroduce Alembic — it was removed to stop drift between
> two competing systems, and the embedded/desktop mode needs self-healing without
> external tooling.

#### Full-text search (FTS5)

- Virtual table `entries_fts` over non-encrypted, non-deleted entry titles + bodies.
- **Seven triggers** keep it in sync, including soft-delete/restore and
  encrypt/decrypt (ciphertext is never indexed): `fts_entry_ai/au/ad`,
  `fts_entry_soft_del`, `fts_entry_restore`, `fts_entry_encrypt`, `fts_entry_decrypt`.
- The **UPDATE** trigger uses `DELETE`+`INSERT` rather than the FTS5 `delete` command
  (a `pysqlite3` workaround).
- `_FTS_REBUILD_VERSION` forces a one-time rebuild to heal historical drift; bump it
  when a trigger change requires re-indexing everything.

### 4.4 Security & encryption (two distinct mechanisms)

**(A) App-level credential encryption — `app/core/security.py`**

Used for OAuth tokens, backup credentials, and AI API keys. Key derived from
`SECRET_KEY`:

- **v2 (current):** HKDF-SHA256, base64 payload prefixed `0x02`.
- **v1 (legacy):** null-padded `SECRET_KEY`, no prefix — still readable for
  backward-compat; `POST /backup/config/migrate-credentials` upgrades v1 → v2 lazily on
  write.
- Cipher: **AES-256-GCM**, random 12-byte nonce per call.

> ⚠️ `SECRET_KEY` is the root key for *all* encrypted credentials. Losing it (deleting
> `.secret_key`) makes stored cloud tokens/backup creds undecryptable. The packaged
> launcher generates and persists it automatically; bare `python -m app.main` does **not**.

**(B) User-passphrase entry/note encryption — `app/services/encryption_service.py`**

The "Encrypt this entry" feature. Key is derived from the **user's passphrase** with a
**memory-hard `scrypt`** KDF (N=2¹⁵, r=8, p=1 ≈ 32 MiB, ~0.1–0.3 s), with a per-item
random salt; cipher is **AES-256-GCM**; payload prefixed `v2:`. (Legacy v1 entries are
still readable.) The scrypt KDF was introduced specifically to make brute-force of
short passphrases expensive.

### 4.5 AI provider abstraction (`app/services/ai_provider_service.py`)

All cloud presets speak the **OpenAI chat-completions API**, so one adapter serves them
all. `PROVIDER_PRESETS` defines: **OpenAI, Groq, OpenRouter, Kimi (Moonshot), Google
Gemini**, the local **`ollama`** preset, and **Custom**.

**Resolution on each AI call:**

1. Look up the DB row with `is_active=True` (cached in `_active_cache`).
2. If found and its preset isn't `ollama`, route to that cloud endpoint.
3. **Otherwise fall back to local Ollama.**

This means **Ollama is always the floor** — if a cloud provider is unreachable or none
is active, AI still works locally. API keys are encrypted via `security.encrypt()` and
never returned by the API.

**Two families of tools:**

- **Named endpoints** (`/ai/grammar-check`, `/ai/rewrite`, `/ai/change-voice`, …) —
  bespoke prompt + response shape each.
- **Generic registry** `POST /ai/tool/{tool_id}` — prompt builders live in
  `app/services/ai_tool_registry.py`; result returned as plain text. Tools:
  `summarize`, `key-points`, `action-items`, `shorten`, `simplify`, `polish`,
  `translate`, `add-structure`, `title`.

### 4.6 Background enrichment (`app/services/enrichment_service.py`)

After an entry is saved, the service fires `asyncio.create_task(...)` (tracked in
`_pending_tasks` so shutdown can cancel it). The pipeline, guarded by per-feature
toggles:

1. **Embeddings** (if enabled) → stored for semantic search.
2. `asyncio.gather` of **sentiment** → `entry_sentiment`, **summary** →
   `entries.summary`, **reflection prompts** → `entry_prompts`.
3. **Tag suggestions** surfaced as pills.

**Graceful degradation:** if AI is unavailable, enrichment returns silently — saving
the entry never fails because of AI.

### 4.7 Cloud OAuth providers (`app/routers/_oauth_helpers.py`)

The four provider routers (`google_drive.py`, `onedrive.py`, `dropbox.py`, `box.py`)
share one flow via `_oauth_helpers.py`:

1. `GET /backup/{provider}/auth-url` — builds the consent URL with a CSRF `state`
   token (`OAuthStateStore`).
2. Browser signs in at the provider; it redirects to the **loopback callback**
   `http://127.0.0.1:18765/api/v1/backup/{provider}/callback` (the web launcher
   prefers 18765 *so this round-trip completes locally*).
3. `exchange_authorization_code()` swaps the code for tokens.
4. `upsert_backup_config()` **encrypts** the credentials and upserts the
   `backup_config` row. Tokens auto-refresh on use.

**WebDAV / Synology NAS** skip OAuth — credentials are entered manually and stored via
`POST /backup/config` (`provider: "webdav"`; Synology is stored as `webdav`).

### 4.8 Scheduler & reminders (`app/services/scheduler_service.py`, `reminder_service.py`)

Reminders are driven by a global **APScheduler `AsyncIOScheduler`**, created lazily and
started in the lifespan.

- **Always go through `ReminderService`** for reminder CRUD — its
  `sync_reminders()` reconciles APScheduler jobs with the DB on startup and after every
  change (removes jobs for inactive/deleted reminders, (re)adds `CronTrigger` jobs for
  active ones). Never schedule a reminder job by hand.
- **Catch-up on boot:** for each active reminder, `schedule_catchup` checks — via
  `core/cron_utils.last_scheduled_occurrence()` — whether its time passed while the app
  was offline and fires it once. Cron math (day-of-week by name or int, walking back up
  to 37 days) is isolated in `cron_utils.py` and unit-tested.

### 4.9 Other service-layer conventions

- **Soft delete + media cleanup:** entries/notes set `is_deleted`; deleting also removes
  the associated media files from disk (`entry_service.py`).
- **Body-size limits:** `max_length=1_000_000` on `EntryCreate.body`; 25 MiB media cap.
- **SSRF hardening** (`web_clip_service.py`): `_ip_is_internal()` blocks
  private/loopback/link-local; a DNS-rebinding guard resolves the host and re-checks;
  an `httpx` event hook re-validates **every redirect hop**.
- **Importers** (`services/importers/`): each external format (Diarium `.diary` SQLite,
  JSON, Markdown ZIP, CSV) is a separate parser; export builders mirror them
  (`export_service.py`, `notes_export_service.py`).
- **Async-ORM gotcha:** `refresh()` does **not** reload `selectin`-loaded relationships,
  and assigning a many-to-many collection raises `MissingGreenlet`. The read paths use
  `selectin` batching (≈6 queries, not N+1); M2M writes go through explicit join-table
  inserts after a `_reload`.

---

## 5. Frontend Deep-Dive

### 5.1 Bootstrap & routing

`main.ts` creates the Vue app, installs **Pinia** + **Vue Router**, runs a one-time
`migrateLegacyKeys()` (localStorage key rename), and mounts. `App.vue` composes the
`AppShell` layout, a `SystemHealthBanner`, the splash screen, the memorial-audio
handler, and `installExternalLinkInterceptor()`.

Routes (`router.ts`): `/` → `/calendar`; plus `/timeline`, `/notes`, `/reminders`,
`/media`, `/settings`. There is intentionally **no `views/` directory** — screens are
assembled from components under `components/<feature>/`.

### 5.2 API layer (`src/api/`)

A single `request()` wrapper in `client.ts` handles fetch, JSON, FormData, and error
propagation. **Backend origin discovery:**

- **Tauri** (detected via `__TAURI_INTERNALS__`): `http://127.0.0.1:18765`.
- **Dev/Web:** relative URLs — Vite proxies `/api` to the backend in dev; in the web
  build the backend serves the SPA directly.

A readiness poller retries the backend (30 × 500 ms) before the app makes real calls.
Domain modules (`entries.ts`, `notes.ts`, `ai.ts`, `search.ts`, `settings.ts`,
`system.ts`, `media.ts`, `tts.ts`, `tags.ts`, `reminders.ts`, `backup.ts`, `export.ts`,
`templates.ts`) each export a typed API object.

### 5.3 State — Pinia stores (`src/stores/`)

| Store | Responsibility |
|---|---|
| `entries` | Calendar entries, current entry, CRUD |
| `notes` | Notes list, folders, current note, pagination |
| `ui` | Active view, sidebar, editor state, drawer panel, **zen mode** |
| `tts` | Shared audio player + loading/playing state |
| `search` | Results, history, search mode |
| `tags` | Tag tree, CRUD |
| `backup` | Backup configs, snapshots, last result |
| `systemHealth` | Integrity report, issue counts, banner |
| `reminders` | Reminder list, CRUD, test notification |
| `templates` | Template list, CRUD |

### 5.4 Composables (`src/composables/`)

The editor is built from small composables: `useRichTextEditor`, `useEditorHistory`
(undo/redo), `useAutoSave`, `useFindReplace`, `useAttachments`, `useRecordings`,
`useMarkdownPreview`, plus utilities (`useCalendar`, `useDragDrop`, `useFormat`,
`usePagination`, `useUpdateChecker`).

**The AI-tool registry** (`aiToolRegistry.ts`) is the single source of truth for the
editor's AI actions. Each entry is `{ id, label, icon, endpoint, resultField, param? }`.
The **AI drawer**, the **right-click context menu**, and `useAiTools.ts` all iterate
this array — adding a tool is a one-line registry entry (front) + a prompt builder
(back), not new UI boilerplate. `useAiTools` handles selection, parameters
(tone/voice/language), and the result actions (`replace` / `insert` / `copy`).

### 5.5 Component organization (`src/components/`)

Feature-grouped folders: `layout/` (AppShell, Sidebar, PanelSplitter, SplashScreen),
`calendar/`, `entry/` (EntryDetail, EntryEditor, AiDrawerPanel, AttachmentsPanel),
`notes/` (NotesView, NoteEditor, NoteTree), `timeline/`, `media/`, `search/`
(SearchPalette), `settings/` (SettingsView + `tabs/` + `dialogs/`), `tags/`,
`reminders/`, `templates/`, `scribble/`, `common/`.

### 5.6 Version injection & external links

- **`version.ts`:** `APP_VERSION` is read from `import.meta.env.VITE_APP_VERSION`
  (injected at build time from `Cargo.toml`), so the **About** tab always matches the
  installed bundle without a backend round-trip.
- **External links** (`utils/externalLink.ts`): `openExternal()` uses the Tauri shell
  plugin in the desktop app and `window.open()` otherwise; a global **capture-phase**
  click handler intercepts `http(s):/mailto:/tel:` links. Email/message views use a
  sandboxed `<iframe>` that `postMessage`s link clicks out to the same handler.

### 5.7 Code-splitting

`AppShell` async-loads heavy panels (`AiDrawerPanel`, `AttachmentsPanel`,
`WhatsNewDialog`) via `defineAsyncComponent`. In Tauri this is nearly free (local disk)
and kept the entry chunk small at startup.

---

## 6. Desktop (Tauri) Deep-Dive

### 6.1 Layout & Cargo features (`desktop/src-tauri/`)

Single binary entry point `src/main.rs` (no `lib.rs`). `Cargo.toml` declares:

```toml
default = ["snip"]            # screen capture ON by default
devtools = ["tauri/devtools"] # webview inspector — intentionally NOT in default
snip     = ["dep:xcap"]       # needs libpipewire-0.3-dev to build on Linux
```

> `devtools` is excluded from `default` deliberately, so the webview inspector **never
> ships in a release build** of a privacy-first app. The original README's
> `default = ["devtools","snip"]` was a documentation error — corrected.

`tauri.conf.json` points the webview at `../../frontend/dist` (dev URL `:5173`), and
declares the backend as an **external binary** `lifelogr-backend`.

### 6.2 The backend sidecar

`desktop/scripts/pyinstaller.spec` freezes the FastAPI app + all deps (Pillow,
pytesseract, edge-tts, sounddevice/soundfile, pysqlite3-binary) into a single
`lifelogr-backend` binary, excluding heavy unused packages (torch, scipy, matplotlib).

Tauri's `main.rs` manages the sidecar lifecycle:

- **Port:** `backend_port()` reads `DIARI_PORT`, else **18765**.
- **Reclaim:** on startup it kills any stale backend still bound to the port
  (owner-verified via `lsof`/`fuser` on Linux).
- **Wait for health:** polls `GET /health` until ready before loading the webview.
- **Graceful shutdown:** `SIGTERM` → fallback `SIGKILL`.

### 6.3 Tauri commands / IPC

| Command | Purpose |
|---|---|
| `check_deps` | Detect Ollama, GStreamer, Tesseract. |
| `run_setup` | First-run system-setup script (Linux, via `pkexec`). |
| `capture_screen` | Screen snip — **feature-gated on `snip`**. |

**Screen-snippet flow:** the global hotkey **`Ctrl+Shift+S`** (`Cmd+Shift+S` on macOS)
emits a `snip-requested` event; `capture_screen` waits ~500 ms for the compositor, grabs
the primary monitor via **`xcap`**, and returns a PNG the frontend crops and uploads.
Built without `snip`, the command returns a friendly error (web-clip image capture and
the text fallback still work).

### 6.4 Build outputs

`desktop/Makefile`: `build-frontend` (VITE_APP_VERSION injection) → `build-backend`
(PyInstaller) → `build-sidecar` (copy to the target-triple path) → `build` (Tauri
bundle). Outputs: **AppImage + deb** (Linux), **dmg** (macOS), **msi** (Windows). Deb
`Depends` pull `tesseract-ocr`, gstreamer plugins, `libportaudio2`, `psmisc`.

> The **web build** (`scripts/build-web-deb.sh`) is the *no-Tauri* path: it ships the
> backend source + built SPA + a bundled `uv`, **builds the venv at install time**,
> generates the `SECRET_KEY`, and installs an on-demand launcher that picks a free port
> (preferring 18765) and runs `uvicorn` as the desktop user.

---

## 7. Data-Flow Walkthroughs

### 7.1 Write & enrich an entry

```
Editor  ──PATCH /entries/{id}──▶  entries.py  ─▶  entry_service.update()
   │                                   │                │
   │                                   │           (DB write + FTS triggers)
   │                                   │                │
   │                                   └─▶ enrichment_service.fire(entry_id)
   │                                                     │ asyncio.create_task
   │                                                     ▼
   │                              [embeddings · sentiment · summary · prompts · tags]
   │                                                     │ (AI: cloud-if-active, else Ollama)
   ◀── 200 EntryResponse ────────────────────────────────┘
   (later: store re-fetch shows AI summary/tags pills)
```

### 7.2 Hybrid search

```
SearchPalette ──GET /search?q=…&mode=hybrid──▶ search_service
                                                     │
                            ┌────────────────────────┴───────────────────────┐
                            ▼                                                 ▼
                   FTS5 BM25 keyword results                          embedding cosine
                                                                     (nomic-embed-text,
                                                                      or cloud if active)
                            └─────────────────► Reciprocal Rank Fusion ◄──────┘
                                                     ▼
                                        unified ranked items (entries + notes)
```

### 7.3 Connect a cloud backup provider (OAuth)

```
Settings → Backup ──GET /backup/google-drive/auth-url──▶ backend (builds URL + state)
      │
      └─ browser opens provider consent ──▶ provider redirects to
                 http://127.0.0.1:18765/api/v1/backup/google-drive/callback?code=…&state=…
                                                      │
                          exchange_authorization_code()│  upsert_backup_config()
                                                      ▼
                              encrypted credentials in backup_config  ◀── success page
```

### 7.4 Screen snip → OCR (desktop)

```
Ctrl+Shift+S ──▶ Tauri emits "snip-requested" ──▶ frontend hides app, invokes capture_screen
                                                          │ (xcap PNG)
                                                          ▼
                          crop overlay ──▶ upload image ──▶ POST /notes/{id}/media
                                                          │
                                                          ▼
                              POST /notes/{id}/media/{media_id}/ocr  (Tesseract, local)
                                                          ▼
                          recognized text inserted as collapsible 📷 OCR block (FTS-indexed)
```

---

## 8. Configuration, Secrets & Data Locations

### Environment variables (`backend/.env.example`)

| Variable | Purpose |
|---|---|
| `APP_ENV` | `production` enables rate limiting + hides `/docs`. |
| `SECRET_KEY` | Root AES key for encrypted credentials. **Required for non-launcher runs.** |
| `CORS_ORIGINS` | Allowed origins (dev). |
| `DATA_DIR` / `LIFELOGR_DATA_DIR` (`DIARI_DATA_DIR`) | Override the data directory. |
| `DATABASE_URL` | Auto-derived from `DATA_DIR` if unset. |
| `RATE_LIMIT` | Production rate limit (default `60/minute`). |
| `MAX_MEDIA_SIZE_BYTES` | 25 MiB default. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` / `OLLAMA_TIMEOUT_SECONDS` | Local AI. |
| `AI_ENABLE_*` | Per-feature enrichment toggles. |
| `GOOGLE_CLIENT_ID/SECRET`, `ONEDRIVE_*`, `DROPBOX_*`, `BOX_*` | OAuth app credentials for cloud backup. |
| `DIARI_PORT` | Tauri sidecar backend port (default 18765). |
| `VITE_BACKEND_PORT` | Dev: Vite proxy target. |
| `VITE_APP_VERSION` | Build-time version injected into the SPA. |

### `.secret_key` lifecycle

- **Packaged launches** (desktop sidecar / web `.deb`): if `<data-dir>/.secret_key`
  doesn't exist, generate `secrets.token_hex(32)`, persist it mode `0600`, and use it.
- **Bare `python -m app.main`:** uses the (insecure) default unless `SECRET_KEY` is set
  — production validation rejects the default.

### Per-build data directories

| Build | Default data dir |
|---|---|
| Desktop (Tauri) | `~/.local/share/com.lifelogr.desktop/` |
| Web / dev | `~/.local/share/lifelogr/` |

Contents: `lifelogr.db`, `.secret_key` (never delete), `media/`, `tts/`, `backups/`,
`server.log` (web only). Relocate via **Settings → Data → Storage location** — it writes
the override file and moves the directory (carrying `.secret_key`).

---

## 9. Build, Release & CI Pipeline

### Top-level `Makefile`

| Target | Purpose |
|---|---|
| `setup` | `uv sync` (backend) + `npm install` (frontend). |
| `run` | `uv run uvicorn app.main:app --reload` (dev server). |
| `test` | Backend `pytest`. |
| `lint` | `ruff check` + `mypy` (strict). |
| `bump V=x.y.z` | Bump version in **all four** sources (see below). |
| `check-version` | Fail if the four versions drift. |
| `domain`/`reqs`/`spec`/`review`/`design`/`code`/`review-code` | SDD pipeline phases (p0–p5.5). |
| `clean` / `all` | Remove caches / run the full SDD pipeline. |

### Versioning (4 sources, kept in sync)

`make bump V=x.y.z` updates:

1. `backend/pyproject.toml`
2. `backend/app/core/config.py` (`APP_VERSION`)
3. `desktop/src-tauri/Cargo.toml`
4. `desktop/src-tauri/tauri.conf.json`

`scripts/check_version.py` enforces parity in CI. `VITE_APP_VERSION` is derived from
`Cargo.toml` and passed to the frontend build (`desktop/Makefile`,
`scripts/build-web-deb.sh`), so the in-app About version always matches the bundle.

### Desktop build (`desktop/Makefile`)

`install` (Rust + Node + Python deps) → `build-frontend` → `build-backend`
(PyInstaller) → `build-sidecar` → `build` (Tauri bundle). `setup` installs Linux system
deps (WebKit + PipeWire). Build without the snip feature on machines lacking
`libpipewire-0.3-dev`: `cargo tauri build --no-default-features`.

### Web build (`scripts/build-web-deb.sh`)

Builds the SPA (with `VITE_APP_VERSION`) → stages backend source + locked
`requirements.txt` + bundled `uv` → assembles `/opt/lifelogr/` → generates the `DEBIAN/`
control scripts. At **install time** `lifelogr-setup` creates the venv with the target
Python; the launcher generates the `SECRET_KEY`, records pid+port for single-instance
enforcement, and prefers port 18765.

### CI (`.github/workflows/`)

**`ci.yml`** — the merge gate (all required on `main`):

| Job | Checks |
|---|---|
| `backend` | ruff, **mypy strict**, pytest with **coverage gate `fail_under = 62`**. |
| `frontend` | `vue-tsc` typecheck, **vitest** unit tests, production build. |
| `e2e-settings` | Playwright e2e (settings / entries / recordings). |
| `version-parity` | `check_version.py` across the 4 sources. |
| `rust-shell` | `cargo check` on the Tauri shell (catches Rust breaks early). |

Rust builds are cached via `Swatinem/rust-cache@v2` (keyed on `desktop/src-tauri`).

**`build.yml`** — release artifacts (gated by `ci.yml`): Linux AppImage+deb, Windows
msi, macOS dmg (Intel, for Rosetta compatibility).

> `origin/main` is protected; direct push is rejected. Work on a `feature/`/`fix/` branch
> and open a PR — the backend + frontend CI gates must pass to merge.

### Docker (optional server deployment)

`Dockerfile` is a two-stage build (Node 22 → Alpine runtime) running `uvicorn` with one
worker. `docker-compose.yml` binds `127.0.0.1:8000:8000` (loopback-only), mounts `./data`
and `./media`, reads `backend/.env`, and uses `restart: unless-stopped`. *Note: inside
the container the server binds `0.0.0.0` so the port forward works — keep the compose
loopback binding.*

---

## 10. Testing Strategy

| Layer | Tooling | Location |
|---|---|---|
| Backend unit | `pytest`, `pytest-asyncio` (`asyncio_mode=auto`) | `backend/tests/unit/` |
| Backend integration | `pytest` + `httpx` | `backend/tests/integration/` |
| Coverage gate | `coverage`, `fail_under = 62` | `backend/pyproject.toml` |
| Backend types/lint | **mypy strict**, **ruff** (`line-length=100`, `py311`) | `backend/pyproject.toml` |
| Frontend unit | **vitest** (`happy-dom`, `src/**/*.test.ts`) | `frontend/src/**/*.test.ts` |
| Frontend types | `vue-tsc -b` | `frontend/package.json` |
| E2E | **Playwright** (baseURL `127.0.0.1:5173`) | `frontend/tests/*.spec.ts` |

The backend suite covers the high-risk surfaces called out in the changelog: backup
restore path-traversal, FTS restore/encrypt triggers, OAuth token-refresh contracts,
the import parsers/export builders, cloud-restore orchestration, and the cron-occurrence
math. A security review is recommended before merging any new networked endpoint.

---

## 11. Extending LifeLogr (How-To)

### Add a database column or index

1. Add the column to the SQLAlchemy model in `app/models/<thing>.py`.
2. Append `(table, column, "ALTER TABLE … ADD COLUMN …")` to `_COLUMN_MIGRATIONS`
   (or an entry to `_INDEX_MIGRATIONS`) in `app/core/database.py`.
3. If the change needs a full re-index of FTS, bump `_FTS_REBUILD_VERSION`.
4. **Do not** add an Alembic migration.

### Add an AI tool

- **Registry tool** (plain-text result): add a prompt builder to
  `app/services/ai_tool_registry.py`, then a one-line entry `{ id, label, icon,
  endpoint: "/ai/tool/<id>", resultField }` to `frontend/src/composables/aiToolRegistry.ts`.
- **Bespoke tool** (custom response shape): add a route in `routers/ai.py`, a method in
  `services/ollama_service.py` / `ai_provider_service.py`, and a schema in `schemas/ai.py`.

### Add a cloud backup provider (OAuth)

1. Subclass / mirror the flow in `routers/_oauth_helpers.py` (auth-url + callback).
2. Add the provider's token URL, scopes, and refresh logic.
3. Register it in the frontend **Backup** tab (`components/settings/tabs/BackupTab.vue`,
   `providerFields`).
4. Tokens persist encrypted via `security.encrypt()` in `backup_config`.

### Add or change a reminder/scheduled job

**Always** go through `ReminderService` (CRUD) so `sync_reminders()` keeps APScheduler
in sync. Reuse `core/cron_utils.py` for any new cron-occurrence math (and unit-test it).

### Add a new REST resource

`models/<thing>.py` (ORM) → `schemas/<thing>.py` (Pydantic v2) →
`services/<thing>_service.py` (logic) → `routers/<thing>.py` (mount under `/api/v1` in
`main.py`). Follow the soft-delete + media-cleanup + selectin-loading patterns used by
`entry_service.py`.

---

## 12. Conventions & Gotchas

- **No Alembic** — inline `_migrate_schema` is the only migration path. (`AGENTS.md`)
- **Async ORM:** `refresh()` won't reload `selectin` relationships; M2M assignment raises
  `MissingGreenlet` — reload + explicit join-table writes instead.
- **Reminders only via `ReminderService`** — never schedule APScheduler jobs manually.
- **No silent `except: pass`** — always `logger.warning(...)` with context.
- **Soft delete must clean up media files.**
- **SSRF:** every outbound URL fetch must reuse the `web_clip_service` guards
  (internal-IP block + DNS-rebinding + per-redirect-hop re-check).
- **Body limits:** `EntryCreate.body` ≤ 1,000,000 chars; media ≤ 25 MiB.
- **Version parity:** bump all four sources together with `make bump`, never by hand.
- **Commits:** conventional-commit prefixes (`feat:`, `fix:`, `test:`, `docs:`, …);
  **no** `Co-Authored-By: Claude` trailer; never commit on `main`.
- **Packaging:** the desktop build excludes `devtools` from release; `snip` needs
  `libpipewire-0.3-dev` to compile.

---

## 13. Common Development Tasks

```bash
# ── First-time setup ──
make setup                       # backend uv sync + frontend npm install

# ── Run locally (two terminals) ──
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev        # → http://localhost:5173 (proxies /api → :8000)

# ── Quality gates ──
make test                         # backend pytest
make lint                         # ruff + mypy (strict)
cd frontend && npm run test       # vitest
cd frontend && npx playwright test   # e2e (needs backend + vite running)

# ── Build packages ──
cd desktop && make build          # → AppImage + deb
./scripts/build-web-deb.sh        # → dist/lifelogr-web_<ver>_amd64.deb

# ── Release a new version ──
make bump V=0.7.2 && make check-version   # bump + verify parity
git checkout -b release/0.7.2             # main is protected — branch first

# ── Inspect runtime ──
sqlite3 ~/.local/share/com.lifelogr.desktop/lifelogr.db ".tables"   # desktop data
curl http://127.0.0.1:18765/api/v1/system/egress-report              # privacy audit
```

For usage (not internals), see the **[User Manual](manual/USER_MANUAL.md)**; for the
HTTP contract, the **[API Reference](manual/API_REFERENCE.md)**; for packaging details,
the **[Build Guide](BUILD_GUIDE.md)** and **[Deployment Guide](manual/DEPLOYMENT.md)**.
