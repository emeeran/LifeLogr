"""Main FastAPI application entry point."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.exceptions import ConflictError, MediaSizeError, NotFoundError

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("diarilinux")

# Resolve project root (3 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets"
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on startup."""
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.APP_ENV)
    await init_db()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Diarilinux",
    description="Privacy-first, offline-first journaling app for Linux",
    version="0.1.0",
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
async def log_requests(request: Request, call_next):
    req_id = uuid4().hex[:8]
    start = time.time()
    logger.info("[%s] %s %s", req_id, request.method, request.url.path)
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    logger.info("[%s] %s %s → %d (%.1fms)", req_id, request.method, request.url.path, response.status_code, elapsed)
    return response


# ── Rate limiting (simple in-memory) ──
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 60
RATE_WINDOW = 60.0


@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    # Skip rate limiting for static assets, health, and tests
    if request.url.path.startswith(("/static", "/health", "/favicon")):
        return await call_next(request)
    if settings.APP_ENV == "test":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _rate_store[client_ip]
    # Remove entries older than window
    _rate_store[client_ip] = timestamps = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    timestamps.append(now)
    return await call_next(request)


# Serve static assets (logo, etc.)
if _ASSETS_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_ASSETS_DIR)), name="static")

# Serve built frontend in production
if settings.is_production and _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend SPA — fall back to index.html for client-side routing."""
        file_path = _FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

# Exception handlers — map domain exceptions to HTTP responses
app.add_exception_handler(NotFoundError, lambda r, e: JSONResponse(status_code=404, content={"detail": str(e)}))
app.add_exception_handler(ConflictError, lambda r, e: JSONResponse(status_code=409, content={"detail": str(e)}))
app.add_exception_handler(MediaSizeError, lambda r, e: JSONResponse(status_code=400, content={"detail": str(e)}))


# Global exception handler for unhandled errors
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Register routers
from app.routers.ai import router as ai_router  # noqa: E402
from app.routers.analytics import router as analytics_router  # noqa: E402
from app.routers.backup import router as backup_router  # noqa: E402
from app.routers.encryption import router as encryption_router  # noqa: E402
from app.routers.entries import router as entries_router  # noqa: E402
from app.routers.export import router as export_router  # noqa: E402
from app.routers.media import router as media_router  # noqa: E402
from app.routers.prompts import router as prompts_router  # noqa: E402
from app.routers.recordings import router as recordings_router  # noqa: E402
from app.routers.reminders import router as reminders_router  # noqa: E402
from app.routers.revision import router as revision_router  # noqa: E402
from app.routers.search import router as search_router  # noqa: E402
from app.routers.sync import router as sync_router  # noqa: E402
from app.routers.plugins import router as plugins_router  # noqa: E402
from app.routers.tags import router as tags_router  # noqa: E402
from app.routers.templates import router as templates_router  # noqa: E402
from app.routers.tts import router as tts_router  # noqa: E402
from app.routers.video_notes import router as video_router  # noqa: E402

app.include_router(ai_router)
app.include_router(analytics_router)
app.include_router(entries_router)
app.include_router(tags_router)
app.include_router(tts_router)
app.include_router(media_router)
app.include_router(recordings_router)
app.include_router(backup_router)
app.include_router(prompts_router)
app.include_router(encryption_router)
app.include_router(export_router)
app.include_router(reminders_router)
app.include_router(revision_router)
app.include_router(search_router)
app.include_router(sync_router)
app.include_router(plugins_router)
app.include_router(templates_router)
app.include_router(video_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/brand/logo")
async def brand_logo() -> FileResponse:
    """Return the Diarilinux logo SVG."""
    logo_path = _ASSETS_DIR / "diarilinux-logo.svg"
    return FileResponse(path=str(logo_path), media_type="image/svg+xml")


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Diarilinux backend server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=18765, help="Bind port")
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
