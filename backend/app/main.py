"""Main FastAPI application entry point."""

from __future__ import annotations

# Patch sqlite3 with pysqlite3 in PyInstaller builds where the bundled
# sqlite3 has issues with qualified column names (e.g. "entries.title").
import sys

try:
    import pysqlite3 as _pysqlite3  # type: ignore[import-untyped]

    if getattr(sys, "frozen", False):
        sys.modules["sqlite3"] = _pysqlite3
except ImportError:
    import logging

    logging.getLogger(__name__).debug("pysqlite3 not available; using stdlib sqlite3")

import logging
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.exceptions import ConflictError, MediaSizeError, NotFoundError, ValidationError
from app.services.ollama_service import OllamaServiceError

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lifelogr")

# Resolve project root (3 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets"
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on startup, clean up on shutdown."""
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.APP_ENV)
    if settings.SECRET_KEY == "change-me-before-production":
        logger.warning(
            "SECRET_KEY is the default — encrypted credentials (IMAP/SMTP/cloud "
            "OAuth) are keyed off it. Run a deployment that generates a key, or "
            "set SECRET_KEY in .env. (The packaged launcher does this for you.)"
        )
    # Load persisted runtime settings (model selections, feature toggles)
    try:
        from app.routers.settings import load_persisted_settings

        load_persisted_settings()
    except Exception:
        logger.warning("Failed to load persisted settings", exc_info=True)
    await init_db()
    # Startup self-checks (warn-only; never block boot). See app.core.startup_checks.
    try:
        from app.core.startup_checks import check_data_integrity

        await check_data_integrity()
    except Exception:
        logger.warning("Startup data-integrity check failed", exc_info=True)
    # Start backup scheduler
    try:
        from app.services.scheduler_service import SchedulerService

        await SchedulerService.start()
        # Schedule offline catch-up for missed reminders ~30s after boot,
        # giving the DB and scheduler time to settle.
        sched = SchedulerService.get_scheduler()
        if sched.running:
            from datetime import datetime, timedelta
            from apscheduler.triggers.date import DateTrigger

            sched.add_job(
                SchedulerService.schedule_catchup,
                trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=30)),
                id="reminder_catchup",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=120,
            )
    except Exception:
        logger.warning("Failed to start backup scheduler", exc_info=True)
    # Verify the backup system is armed (self-heals a missing auto_backup job).
    try:
        from app.core.startup_checks import check_backup_health

        await check_backup_health()
    except Exception:
        logger.warning("Startup backup-health check failed", exc_info=True)
    yield
    logger.info("Shutting down...")
    # Stop backup scheduler
    try:
        from app.services.scheduler_service import SchedulerService

        await SchedulerService.shutdown()
    except Exception:
        logger.warning("Failed to stop backup scheduler", exc_info=True)
    # Cancel outstanding background enrichment tasks
    try:
        from app.services.enrichment_service import cancel_pending_tasks

        await cancel_pending_tasks()
    except Exception:
        logger.warning("Failed to cancel enrichment tasks", exc_info=True)
    # Dispose database engine
    try:
        from app.core.database import engine

        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        logger.warning("Failed to dispose database engine", exc_info=True)
    # Close shared Ollama HTTP client
    try:
        from app.services.ollama_service import close_shared_client

        await close_shared_client()
    except Exception:
        logger.warning("Failed to close Ollama client", exc_info=True)


app = FastAPI(
    title=settings.APP_NAME,
    description="Your Day in Media & Minutes",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Request logging middleware ──
@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Response:
    # Health checks and static asset polls are noisy; log them at DEBUG only.
    skip = request.url.path.startswith(("/health", "/static", "/favicon"))
    if skip:
        return await call_next(request)  # type: ignore[no-any-return]
    req_id = uuid4().hex[:8]
    start = time.time()
    logger.info("[%s] %s %s", req_id, request.method, request.url.path)
    response: Response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    logger.info(
        "[%s] %s %s → %d (%.1fms)",
        req_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


# ── Rate limiting (simple in-memory) ──
_rate_store: dict[str, list[float]] = defaultdict(list)


def _parse_rate_limit(raw: str) -> tuple[int, float]:
    """Parse 'N/period' (e.g. '60/minute') → (count, window_seconds)."""
    try:
        count_str, period = raw.lower().split("/", 1)
        count = int(count_str)
        window = {"second": 1.0, "minute": 60.0, "hour": 3600.0}.get(period, 60.0)
    except (ValueError, AttributeError):
        return 60, 60.0
    return max(1, count), window


# Driven by settings.RATE_LIMIT (e.g. "60/minute"); falls back to 60/min.
RATE_LIMIT, RATE_WINDOW = _parse_rate_limit(settings.RATE_LIMIT)


@app.middleware("http")
async def rate_limiter(request: Request, call_next: Any) -> Response:
    # Rate limiting only matters for multi-tenant server deployments. The
    # desktop/Tauri sidecar is single-user on loopback, where limiting the
    # user's own bulk imports/enrichment is actively harmful.
    if not settings.is_production:
        return await call_next(request)  # type: ignore[no-any-return]
    # Skip rate limiting for static assets, health, and tests
    if request.url.path.startswith(("/static", "/health", "/favicon")):
        return await call_next(request)  # type: ignore[no-any-return]

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _rate_store[client_ip]
    # Remove entries older than window
    pruned = [t for t in timestamps if now - t < RATE_WINDOW]
    if not pruned:
        _rate_store.pop(client_ip, None)  # prevent memory leak from stale IPs
    _rate_store[client_ip] = timestamps = pruned
    if len(timestamps) >= RATE_LIMIT:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    timestamps.append(now)
    return await call_next(request)  # type: ignore[no-any-return]


# Serve static assets (logo, etc.)
if _ASSETS_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_ASSETS_DIR)), name="static")

# Exception handlers — map domain exceptions to HTTP responses
app.add_exception_handler(
    NotFoundError, lambda r, e: JSONResponse(status_code=404, content={"detail": str(e)})
)
app.add_exception_handler(
    ConflictError, lambda r, e: JSONResponse(status_code=409, content={"detail": str(e)})
)
app.add_exception_handler(
    MediaSizeError, lambda r, e: JSONResponse(status_code=400, content={"detail": str(e)})
)
app.add_exception_handler(
    ValidationError, lambda r, e: JSONResponse(status_code=400, content={"detail": str(e)})
)
app.add_exception_handler(
    OllamaServiceError,
    lambda r, e: JSONResponse(status_code=504, content={"detail": str(e)}),
)


# Global exception handler for unhandled errors
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Register routers
from app.routers.ai import router as ai_router  # noqa: E402
from app.routers.analytics import router as analytics_router  # noqa: E402
from app.routers.backup import router as backup_router  # noqa: E402
from app.routers.contacts import router as contacts_router  # noqa: E402
from app.routers.email import router as email_router  # noqa: E402
from app.routers.google_drive import router as google_drive_router  # noqa: E402
from app.routers.google_sync import router as google_sync_router  # noqa: E402
from app.routers.box import router as box_router  # noqa: E402
from app.routers.dropbox import router as dropbox_router  # noqa: E402
from app.routers.onedrive import router as onedrive_router  # noqa: E402
from app.routers.encryption import (  # noqa: E402
    router as encryption_router,
    global_router as encryption_global_router,
    notes_router as encryption_notes_router,
)  # noqa: E402
from app.routers.entries import router as entries_router  # noqa: E402
from app.routers.notes import router as notes_router  # noqa: E402
from app.routers.export import router as export_router  # noqa: E402
from app.routers.planner import router as planner_router  # noqa: E402
from app.routers.media import router as media_router  # noqa: E402
from app.routers.prompts import router as prompts_router  # noqa: E402
from app.routers.recordings import router as recordings_router  # noqa: E402
from app.routers.reminders import router as reminders_router  # noqa: E402
from app.routers.search import router as search_router  # noqa: E402
from app.routers.sync import router as sync_router  # noqa: E402
from app.routers.tags import router as tags_router  # noqa: E402
from app.routers.templates import router as templates_router  # noqa: E402
from app.routers.tts import router as tts_router  # noqa: E402
from app.routers.video_notes import router as video_router  # noqa: E402
from app.routers.settings import router as settings_router  # noqa: E402
from app.routers.memorial import router as memorial_router  # noqa: E402

app.include_router(ai_router)
app.include_router(analytics_router)
app.include_router(entries_router)
app.include_router(contacts_router)
app.include_router(email_router)
app.include_router(notes_router)
app.include_router(tags_router)
app.include_router(tts_router)
app.include_router(media_router)
app.include_router(recordings_router)
app.include_router(backup_router)
app.include_router(google_drive_router)
app.include_router(google_sync_router)
app.include_router(box_router)
app.include_router(onedrive_router)
app.include_router(dropbox_router)
app.include_router(prompts_router)
app.include_router(encryption_router)
app.include_router(encryption_global_router)
app.include_router(encryption_notes_router)
app.include_router(export_router)
app.include_router(reminders_router)
app.include_router(planner_router)
app.include_router(search_router)
app.include_router(sync_router)
app.include_router(templates_router)
app.include_router(video_router)
app.include_router(settings_router)
app.include_router(memorial_router)


@app.get("/health")
async def health_check() -> Any:
    """Health check — reports DB connectivity plus key subsystem availability.

    Each subsystem is checked independently so a single failure (e.g. Ollama
    not running) degrades gracefully rather than failing the whole probe. The
    overall status is ``ok`` only when the DB (the hard dependency) is up.
    """
    checks: dict[str, str] = {}
    healthy = True

    from sqlalchemy import text

    # 1. Database (hard dependency)
    try:
        from app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error("Health check DB failed: %s", e)
        checks["database"] = "error"
        healthy = False

    # 2. FTS5 (soft — search feature)
    try:
        from app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT count(*) FROM entries_fts"))
        checks["fts"] = "ok"
    except Exception:
        checks["fts"] = "unavailable"

    # 3. Scheduler (soft)
    try:
        from app.services.scheduler_service import SchedulerService

        sched = SchedulerService.get_scheduler()
        checks["scheduler"] = "ok" if sched.running else "stopped"
    except Exception:
        checks["scheduler"] = "unavailable"

    # 4. Ollama (soft — AI features)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception:
        checks["ollama"] = "unreachable"

    # 5. Startup self-checks (soft — last result from boot, not re-run per request).
    try:
        from app.core.startup_checks import get_backup_status, get_integrity_status

        integ = get_integrity_status()
        if not integ.get("ran"):
            checks["integrity"] = "not_checked"
        elif integ.get("ok"):
            checks["integrity"] = "ok"
        else:
            checks["integrity"] = f"fk_violations:{integ.get('fk_violations', -1)}"

        backup = get_backup_status()
        if not backup.get("ran"):
            checks["backup"] = "not_checked"
        elif not backup.get("scheduled"):
            checks["backup"] = "unscheduled"
        elif backup.get("stale"):
            checks["backup"] = "stale"
        else:
            checks["backup"] = "scheduled"
    except Exception:
        checks["integrity"] = "unavailable"
        checks["backup"] = "unavailable"

    if not healthy:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "Database unavailable", "checks": checks},
        )
    return {"status": "ok", "checks": checks}


@app.get("/api/v1/brand/logo")
async def brand_logo() -> FileResponse:
    """Return the LifeLogr logo (PNG preferred, SVG fallback).

    In packaged desktop builds the source ``assets/`` directory is not on
    disk (it is baked into the frontend bundle instead), so both candidates
    may be absent — in that case return a clean 404 rather than crashing.
    """
    png = _ASSETS_DIR / "lifelogr-logo.png"
    svg = _ASSETS_DIR / "lifelogr-logo.svg"
    if png.exists():
        return FileResponse(path=str(png), media_type="image/png")
    if svg.exists():
        return FileResponse(path=str(svg), media_type="image/svg+xml")
    raise NotFoundError("Brand logo not available in this build")


# Serve built frontend in production — MUST be registered AFTER all API routes
# so that API GET requests are matched before this catch-all.
if _FRONTEND_DIST.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend-assets"
    )

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> FileResponse:
        """Serve frontend SPA — fall back to index.html for client-side routing."""
        file_path = _FRONTEND_DIST / full_path
        target = file_path if file_path.is_file() else (_FRONTEND_DIST / "index.html")
        # index.html must always revalidate so new content-hashed assets are
        # picked up; the hashed asset files themselves can be cached forever.
        is_index = target.name == "index.html"
        headers = (
            {"Cache-Control": "no-cache, must-revalidate"}
            if is_index
            else {"Cache-Control": "public, max-age=31536000, immutable"}
        )
        return FileResponse(str(target), headers=headers)


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="LifeLogr backend server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=18765, help="Bind port")
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
