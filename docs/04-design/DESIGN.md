# Architecture Design — Diarilinux

> Phase 4: Design derived from [SPEC.md](../02-spec/SPEC.md) and [REVIEW.md](../03-review/REVIEW.md) (PASS).
> Stack: FastAPI, SQLAlchemy 2.x, Pydantic v2, SQLite, `uv`.

---

## Component Diagram

```mermaid
graph TB
    subgraph core["app.core"]
        config["app.core.config"]
        database["app.core.database"]
        security["app.core.security"]
    end

    subgraph routers["app.routers"]
        entries_router["app.routers.entries"]
        tags_router["app.routers.tags"]
        media_router["app.routers.media"]
        recordings_router["app.routers.recordings"]
        backup_router["app.routers.backup"]
        prompts_router["app.routers.prompts"]
    end

    subgraph services["app.services"]
        entry_svc["app.services.entry_service"]
        tag_svc["app.services.tag_service"]
        media_svc["app.services.media_service"]
        recording_svc["app.services.recording_service"]
        backup_svc["app.services.backup_service"]
        prompt_svc["app.services.prompt_service"]
    end

    subgraph models["app.models"]
        entry_model["app.models.entry"]
        tag_model["app.models.tag"]
        media_model["app.models.media"]
        recording_model["app.models.recording"]
        backup_model["app.models.backup"]
        prompt_model["app.models.prompt"]
    end

    subgraph schemas["app.schemas"]
        entry_schema["app.schemas.entry"]
        tag_schema["app.schemas.tag"]
        media_schema["app.schemas.media"]
        recording_schema["app.schemas.recording"]
        backup_schema["app.schemas.backup"]
        prompt_schema["app.schemas.prompt"]
    end

    main["app.main"]

    main --> entries_router
    main --> tags_router
    main --> media_router
    main --> recordings_router
    main --> backup_router
    main --> prompts_router

    entries_router --> entry_svc
    tags_router --> tag_svc
    media_router --> media_svc
    recordings_router --> recording_svc
    backup_router --> backup_svc
    prompts_router --> prompt_svc

    entry_svc --> entry_model
    entry_svc --> tag_svc
    entry_svc --> media_svc
    tag_svc --> tag_model
    media_svc --> media_model
    recording_svc --> recording_model
    recording_svc --> media_svc
    backup_svc --> backup_model
    backup_svc --> security
    prompt_svc --> prompt_model

    entries_router --> entry_schema
    tags_router --> tag_schema
    media_router --> media_schema
    recordings_router --> recording_schema
    backup_router --> backup_schema
    prompts_router --> prompt_schema

    entry_model --> database
    tag_model --> database
    media_model --> database
    recording_model --> database
    backup_model --> database
    prompt_model --> database

    database --> config
    security --> config
```

### Import Rules

| From | To | Allowed |
|------|----|---------|
| `app.main` | `app.routers.*`, `app.core.*` | Yes |
| `app.routers.*` | `app.services.*`, `app.schemas.*` | Yes |
| `app.routers.*` | `app.models.*` | **No** — go through services |
| `app.services.*` | `app.models.*`, `app.core.*` | Yes |
| `app.services.*` | `app.schemas.*` | **No** — services return ORM objects; routers convert to schemas |
| `app.models.*` | `app.core.database` | Yes (Base, engine import) |
| `app.schemas.*` | anything | **No** — pure Pydantic, no imports from other app layers |

---

## Sequence Diagrams

### 1. Write Operation — Create Entry with Tags

```mermaid
sequenceDiagram
    participant Client
    participant Router as entries_router
    participant EntrySvc as EntryService
    participant TagSvc as TagService
    participant DB as SQLite

    Client->>Router: POST /api/v1/entries {entry_date, body, mood, tag_ids}
    Router->>Router: Validate request via EntryCreate schema
    Router->>EntrySvc: create(EntryCreate)
    EntrySvc->>DB: BEGIN
    EntrySvc->>DB: INSERT INTO entries (entry_date, body, mood)
    alt entry_date already exists
        DB-->>EntrySvc: IntegrityError
        EntrySvc-->>Router: raise Conflict (409)
        Router-->>Client: 409 Conflict
    end
    EntrySvc->>TagSvc: associate(entry_id, tag_ids)
    TagSvc->>DB: INSERT INTO entry_tags (entry_id, tag_id) ...
    TagSvc-->>EntrySvc: void
    EntrySvc->>DB: COMMIT
    EntrySvc-->>Router: Entry (ORM)
    Router->>Router: Convert to EntryResponse schema
    Router-->>Client: 201 Created {EntryResponse}
```

### 2. Paginated List Query — Browse Entries

```mermaid
sequenceDiagram
    participant Client
    participant Router as entries_router
    participant EntrySvc as EntryService
    participant DB as SQLite

    Client->>Router: GET /api/v1/entries?offset=0&limit=20&tag_ids=1,3
    Router->>Router: Parse and validate query params
    Router->>EntrySvc: list_entries(offset=0, limit=20, tag_ids=[1,3])
    EntrySvc->>DB: SELECT COUNT(*) FROM entries JOIN entry_tags WHERE ...
    DB-->>EntrySvc: total=42
    EntrySvc->>DB: SELECT entries.* FROM entries JOIN entry_tags ... LIMIT 20 OFFSET 0
    DB-->>EntrySvc: rows [0..19]
    EntrySvc-->>Router: (entries_list, total=42)
    Router->>Router: Convert each to EntryResponse
    Router-->>Client: 200 OK {items: [...], total: 42, offset: 0, limit: 20}
```

### 3. Background Task — Incremental Backup

```mermaid
sequenceDiagram
    participant Client
    participant Router as backup_router
    participant BackupSvc as BackupService
    participant Security as app.core.security
    participant Provider as Cloud Provider
    participant DB as SQLite

    Client->>Router: POST /api/v1/backup/run {config_id}
    Router->>BackupSvc: run_backup(config_id)
    BackupSvc->>DB: INSERT INTO backup_snapshots (status='pending')
    BackupSvc->>DB: UPDATE backup_snapshots SET status='in_progress'
    Router-->>Client: 202 Accepted {BackupSnapshotResponse}

    Note over BackupSvc,Provider: Background execution
    BackupSvc->>DB: SELECT * FROM backup_config WHERE id=config_id
    BackupSvc->>Security: decrypt(credentials_encrypted)
    Security-->>BackupSvc: credentials dict
    BackupSvc->>DB: SELECT entries WHERE updated_at > last_sync_at
    BackupSvc->>DB: SELECT media WHERE created_at > last_sync_at
    BackupSvc->>Provider: PUT /upload (entries + media delta)
    Provider-->>BackupSvc: 200 OK

    alt Success
        BackupSvc->>DB: UPDATE backup_snapshots SET status='completed', completed_at=now
        BackupSvc->>DB: UPDATE backup_config SET last_sync_at=now
    else Failure
        BackupSvc->>DB: UPDATE backup_snapshots SET status='failed', error_message=...
    end
```

---

## Module File Map

```
backend/app/
├── main.py                          # FastAPI app factory, router registration, CORS
├── core/
│   ├── __init__.py
│   ├── config.py                    # Settings via pydantic-settings (DATABASE_URL, MEDIA_DIR, etc.)
│   ├── database.py                  # SQLAlchemy async engine, sessionmaker, Base
│   └── security.py                  # AES-256-GCM encrypt/decrypt for credentials
├── routers/
│   ├── __init__.py
│   ├── entries.py                   # Journal CRUD + calendar + search
│   ├── tags.py                      # Tag CRUD + tree
│   ├── media.py                     # Media upload/download/delete
│   ├── recordings.py                # Voice recording upload/transcribe/delete
│   ├── backup.py                    # Backup config, run, restore, snapshots
│   └── prompts.py                   # Daily prompt
├── models/
│   ├── __init__.py                  # Re-export all models for Alembic discovery
│   ├── entry.py                     # Entry ORM
│   ├── tag.py                       # Tag + EntryTag ORM
│   ├── media.py                     # Media ORM
│   ├── recording.py                 # VoiceRecording ORM
│   ├── backup.py                    # BackupConfig + BackupSnapshot ORM
│   └── prompt.py                    # DailyPrompt ORM
├── schemas/
│   ├── __init__.py
│   ├── entry.py                     # EntryCreate, EntryUpdate, EntryResponse, EntryListResponse
│   ├── tag.py                       # TagCreate, TagUpdate, TagBrief, TagResponse
│   ├── media.py                     # MediaCreate, MediaResponse
│   ├── recording.py                 # VoiceRecordingResponse, TranscriptionRequest
│   ├── backup.py                    # BackupConfigCreate/Response, BackupSnapshotResponse, RestoreRequest
│   └── prompt.py                    # PromptResponse
└── services/
    ├── __init__.py
    ├── entry_service.py
    ├── tag_service.py
    ├── media_service.py
    ├── recording_service.py
    ├── backup_service.py
    └── prompt_service.py
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DB sessions | Per-request `Depends(get_db)` via FastAPI dependency injection | Ensures clean session lifecycle; auto-closes on response |
| ORM style | SQLAlchemy 2.x mapped dataclasses (`DeclarativeBase`) | Type-safe, IDE-friendly, matches SPEC requirement |
| File storage | Local filesystem under `MEDIA_DIR` with UUID filenames | Simple, portable, avoids DB bloat; path stored in `media.storage_path` |
| Backup execution | `BackgroundTasks` from FastAPI | Single-user app; no need for Celery/Redis. Backup runs in-process |
| Transcription | `whisper` (OpenAI local model) via subprocess | Runs on-device, no API key needed, matches FR-018 |
| Encryption | AES-256-GCM via `cryptography` library | Standard, audited, matches NFR-005 |
| Error handling | Service layer raises domain exceptions; routers catch and map to HTTP | Clean separation; services never import FastAPI |
| Config | `pydantic-settings` reading `.env` | Type-safe config with validation, matches CLAUDE.md convention |

---

## Dependency Injection

```python
# app/core/database.py
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

# app/routers/entries.py
@router.post("/api/v1/entries", response_model=EntryResponse, status_code=201)
async def create_entry(data: EntryCreate, db: AsyncSession = Depends(get_db)):
    svc = EntryService(db)
    entry = await svc.create(data)
    return entry
```

Services are instantiated per-request with the injected session. No global singletons.

---

## Directory Layout for Media Storage

```
MEDIA_DIR/
├── images/
│   └── {uuid}.{ext}
├── videos/
│   └── {uuid}.{ext}
├── audio/
│   └── {uuid}.{ext}
└── documents/
    └── {uuid}.{ext}
```

Files are named by UUID to avoid collisions. Original filename preserved in `media.filename`. `media.storage_path` stores the relative path from `MEDIA_DIR`.

---

## Error Mapping Strategy

```python
# app/core/exceptions.py
class NotFoundError(Exception): ...
class ConflictError(Exception): ...
class ValidationError(Exception): ...
class MediaSizeError(Exception): ...

# app/main.py — global exception handlers
@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})

@app.exception_handler(ConflictError)
async def conflict_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

Services raise domain exceptions. Routers don't need try/except — the global handlers map them to HTTP responses.

---

## Review Minor Fixes Incorporated

| Minor | Design resolution |
|-------|-------------------|
| 001 — GET /tags errors | Invalid `parent_id` returns empty list (no 404 needed for optional filter) |
| 002 — GET /backup/snapshots errors | FastAPI auto-validates offset/limit → 422; invalid `config_id` returns empty list |
| 003 — credentials as dict | Kept as `dict[str, str]` — provider credential schemas differ too much to union; validation happens in service layer per-provider |
| 004 — missing pagination notes | Tree/calendar are bounded; documented in DESIGN |
| 005 — missing examples | Will be added during implementation (p5) |
| 006 — no out-of-scope section | Linked from REQUIREMENTS.md; not duplicated in design |

---

## Future Performance & Reliability Enhancements

To sustain single-user scaling and local ML inference throughput, the following architectural upgrades are slated for implementation:

### 1. Concurrency Optimization in Inference Services
*   **Target:** `VoiceRecordingService._run_stt`, `OCRService.extract_text`, and `VideoService.transcribe`.
*   **Resolution:** Offload CPU-intensive operations (Whisper transcription, Tesseract process execution) from the main ASGI thread to a separate threadpool using `asyncio.to_thread`. This guarantees that long-running inferences will not block FastAPI's primary event loop.

### 2. Video STT Memory Management
*   **Target:** `VideoService.transcribe`.
*   **Resolution:** Refactor `VoiceRecordingService` to accept file paths directly, avoiding loading raw video files (often exceeding 100MB+) into active RAM as `bytes`.

### 3. Filter Propagation to Vector Indexes
*   **Target:** `SearchService._semantic_search`.
*   **Resolution:** Integrate SQL filter generators directly into the SQL select statements preceding embedding computations. Instead of running full in-memory cosine similarity comparisons across the entire database, pre-filtering by tags, mood, or dates will narrow down candidates significantly.

### 4. Connection Pool Audits
*   **Target:** `NextcloudProvider` and `GoogleDriveProvider`.
*   **Resolution:** Expand `SyncProvider` with an explicit `close()` protocol method, and utilize context manager lifecycles inside orchestration routines to cleanly tear down shared `httpx.AsyncClient` socket connection pools.

