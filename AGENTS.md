# LifeLogr — Agent Context

## Project Purpose
> LifeLogr is a privacy-first, local-first **journaling + notes** app for Linux
> (Ubuntu 24.04). It provides a rich markdown writing experience with media
> attachments and voice/video clips, on-device OCR (Tesseract), read-aloud (Edge
> TTS), hybrid full-text + semantic search, per-item AES-256-GCM encryption,
> optional encrypted cloud backup (Google Drive, OneDrive, Dropbox, Box,
> WebDAV/Synology), and an AI writing assistant that runs **locally via Ollama by
> default** (optionally any OpenAI-compatible cloud provider). Two builds ship: a
> Tauri desktop app and a browser web app — both single-user, backend bound to
> `127.0.0.1`, all data on disk.

## Tech Stack
| Layer      | Technology                                                          |
|------------|---------------------------------------------------------------------|
| Backend    | Python 3.11+, FastAPI (async), Pydantic v2, SQLAlchemy 2.x          |
| Database   | SQLite (WAL mode, FK enforced) + FTS5 + local embeddings           |
| Frontend   | Vue 3 SPA · Vite · TypeScript · Pinia · TailwindCSS v4              |
| Desktop    | Tauri v2 (Rust) shell + PyInstaller-bundled backend sidecar         |
| AI / OCR   | Ollama (local default; optional cloud), Tesseract OCR, Edge TTS     |
| Packaging  | `uv` for Python (never pip); npm for frontend; cargo for Tauri      |
| Testing    | pytest, httpx, pytest-asyncio; Vitest; Playwright                   |
| Linting    | ruff, mypy (strict); vue-tsc                                        |
| OS         | Ubuntu 24.04 LTS                                                    |

## SDD Pipeline
```
p0: Domain  →  p1: Requirements  →  p2: Spec  →  p3: Review (PASS gate)
→  p4: Design  →  p5: Code  →  p5.5: Code Review  →  p6: Tests
```
**The review gate is hard.** Do not proceed to p4 until p3 outputs PASS.

## Key Commands
```bash
make setup        # Install dependencies
make domain       # Run domain analysis (p0)
make reqs         # Generate requirements (p1)
make spec         # Generate spec (p2)
make review       # Run review gate (p3) — must PASS before continuing
make design       # Generate design (p4)
make code         # Implement code (p5)
make review-code  # Review code for bloat (p5.5)
make test         # Run tests (p6)
make lint         # ruff + mypy
make run          # Start dev server
```

## Project Structure
```
diary/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI entry point
│   │   ├── core/            # Config, DB session, security
│   │   ├── routers/         # Route handlers
│   │   ├── models/          # ORM models
│   │   ├── schemas/         # Pydantic schemas
│   │   └── services/        # Business logic
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── .env                 # Local secrets (never commit)
│   └── pyproject.toml
├── docs/                    # SDD artefacts (00-domain…04-design) + ARCHITECTURE/BUILD_GUIDE + manual/
├── AGENTS.md                # ← You are here
└── Makefile
```

## Conventions
- All secrets go in `backend/.env` — never hardcode.
- `uv add <pkg>` to add dependencies; `uv run pytest` to run tests.
- Commit docs artefacts (DOMAIN.md, SPEC.md, etc.) alongside code.
- Each PR must include updated tests and passing lint.
- SQLite uses WAL mode + FK enforcement automatically (see `database.py` event listener).
- **Schema migrations are inline**, not Alembic: `database.py:_migrate_schema` (`_COLUMN_MIGRATIONS` + `_INDEX_MIGRATIONS`) is the canonical, idempotent desktop migration path. Add new columns/indexes there. (Alembic was removed to avoid drift between two competing systems.)
- **Reminders are APScheduler-driven:** `SchedulerService.sync_reminders()` reconciles per-reminder cron jobs with the DB on startup and after every reminder CRUD op; `schedule_catchup` fires any reminder whose time passed while offline. Never schedule reminders manually — always go through `ReminderService` so jobs stay in sync.
- **FTS5 setup runs in all builds** (including PyInstaller): the `pysqlite3` swap in `app/main.py` fixes the qualified-column bug that previously forced skipping FTS in frozen builds.
- **Tags live in the text:** an entry/note's tags are the `#hashtags` in its body, extracted by `services/hashtag.py` (`extract_hashtags` + `resolve_tag_ids`) and synced on save — client-sent tag ids are **ignored**. The editors expose this with inline `#` autocomplete (`composables/useInlineTags.ts`, `components/editor/TagAutocomplete.vue`).
- **Notes are hierarchical:** `NoteFolder` supports nesting (sub-folders) with an acyclic guard; pages are tabbed sections within a note.
- **DB boot safety:** `core/database` takes a rotating `lifelogr.db.boot-bak-*` snapshot before migrations; if `PRAGMA integrity_check` fails at boot, the newest good snapshot is restored and the corrupt file is quarantined (`_CORRUPT_PREFIX`).
- Never use silent `except: pass` — always log with context (`logger.warning`).
- Backup import validates tar members for path traversal before extraction.
- Soft delete must clean up associated media files (see `entry_service.py`).
- Body size limit: `max_length=1_000_000` on `EntryCreate.body`.
- **Versioning:** `make bump V=x.y.z` updates `backend/pyproject.toml`, `backend/app/core/config.py` (`APP_VERSION`), `desktop/src-tauri/Cargo.toml`, AND `desktop/src-tauri/tauri.conf.json` together (these drive the `.deb`/AppImage filename). The About tab shows the version injected at **frontend build time** via `VITE_APP_VERSION` (see `frontend/src/version.ts`); the build passes it from `Cargo.toml` (`desktop/Makefile` + `.github/workflows/build.yml`), so the UI always matches the bundle without waiting for the backend. The backend's `APP_VERSION` (via `/api/v1/settings`) is the API-consumer source of truth. The `.deb` build auto-generates a `SECRET_KEY`.
- **AI tools are registry-driven:** the editor's AI tools are defined once in `frontend/src/composables/aiToolRegistry.ts` (id/label/icon/endpoint/resultField/param). The AI drawer, right-click context menu, and `useAiTools` composable all iterate it — no per-tool boilerplate. Tools backed by the generic `POST /api/v1/ai/tool/{tool_id}` endpoint also need a prompt builder added to `backend/app/services/ai_tool_registry.py`.
