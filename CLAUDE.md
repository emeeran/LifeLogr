# LifeLogr — Claude Context

## Project Purpose
> LifeLogr is a privacy-first, offline-first daily journaling application for Linux. It provides a rich writing experience with markdown support, media attachments, voice recording with local transcription, AI-assisted grammar checking via Ollama, end-to-end encrypted cloud sync, and a plugin architecture — all while keeping user data local and private.

## Tech Stack
| Layer     | Technology                          |
|-----------|-------------------------------------|
| Backend   | Python 3.11+, FastAPI, Pydantic v2  |
| Database  | SQLite (WAL mode, FK enforced)      |
| Packaging | `uv` (never use pip directly)       |
| Testing   | pytest, httpx, pytest-asyncio       |
| Linting   | ruff, mypy (strict)                 |
| OS        | Ubuntu 24.x                         |

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
├── docs/                    # SDD artefacts
├── prompts/                 # Prompt templates
├── raw_idea.txt
├── CLAUDE.md                # ← You are here
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
- Plugin `entry_point` must be validated (regex + stdlib blocklist in `schemas/plugin.py`).
- Never use silent `except: pass` — always log with context (`logger.warning`).
- Backup import validates tar members for path traversal before extraction.
- Soft delete must clean up associated media files (see `entry_service.py`).
- Body size limit: `max_length=1_000_000` on `EntryCreate.body`.
- **Versioning:** bump the version in `backend/pyproject.toml`, `desktop/src-tauri/Cargo.toml`, AND `desktop/src-tauri/tauri.conf.json` together (these drive the `.deb`/AppImage filename). The version shown in the About tab comes from `APP_VERSION` in `backend/app/core/config.py` (served via `/api/v1/settings`), so update that too or the UI lags behind. The `.deb` build auto-generates a `SECRET_KEY`.
- **AI tools are registry-driven:** the editor's AI tools are defined once in `frontend/src/composables/aiToolRegistry.ts` (id/label/icon/endpoint/resultField/param). The AI drawer, right-click context menu, and `useAiTools` composable all iterate it — no per-tool boilerplate. Tools backed by the generic `POST /api/v1/ai/tool/{tool_id}` endpoint also need a prompt builder added to `backend/app/services/ai_tool_registry.py`.
