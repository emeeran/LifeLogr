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
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import DEFAULT_SECRET_KEY, is_loopback_host, settings
from app.core.database import init_db
from app.core.exceptions import ConflictError, MediaSizeError, NotFoundError, ValidationError
from app.core.security import DefaultSecretKeyError
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
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY:
        logger.warning(
            "SECRET_KEY is the default — encrypted credentials (cloud "
            "OAuth) are keyed off it. Run a deployment that generates a key, or "
            "set SECRET_KEY in .env. (The packaged launcher does this for you.)"
        )
    # Load persisted runtime settings (model selections, feature toggles)
    try:
        from app.services.settings_service import load_runtime_settings

        load_runtime_settings()
    except Exception:
        logger.warning("Failed to load persisted settings", exc_info=True)
    await init_db()
    # Rewrite AI-provider rows still naming a retired model (e.g. Groq's
    # 2026-08-16 decommissions) so stored configs keep working. Warn-only.
    try:
        from app.core.database import async_session
        from app.services.ai_provider_service import apply_deprecated_model_fixups

        async with async_session() as session:
            await apply_deprecated_model_fixups(session)
    except Exception:
        logger.warning("AI-provider model fixup failed", exc_info=True)
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
    # Broad app-integrity battery (DB structure, schema, FTS, encryption-key
    # canary, pool, data dir). Warn-only; surfaced via /api/v1/system/integrity
    # and the startup health banner.
    try:
        from app.core.startup_checks import check_app_integrity

        await check_app_integrity()
    except Exception:
        logger.warning("Startup app-integrity check failed", exc_info=True)
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
_rate_store: dict[str, list[float]] = {}

# Upper bound on tracked clients: once past it, stale keys are swept so an
# attacker rotating source addresses can't grow the map without bound.
_RATE_STORE_MAX_KEYS = 10_000


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
    # Read with .get (never index the dict) so a request from an unseen client
    # can't create an entry that then lingers as an empty list forever.
    timestamps = [t for t in _rate_store.get(client_ip, []) if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        # Retry-After tells the client when the oldest hit ages out of the window.
        retry_after = max(1, int(RATE_WINDOW - (now - timestamps[0])) + 1)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )
    timestamps.append(now)
    _rate_store[client_ip] = timestamps
    # Reclaim memory: drop keys whose window has fully elapsed, and cap the map.
    if len(_rate_store) > _RATE_STORE_MAX_KEYS:
        stale = [k for k, hits in _rate_store.items() if not hits or now - hits[-1] >= RATE_WINDOW]
        for key in stale:
            _rate_store.pop(key, None)
    return await call_next(request)  # type: ignore[no-any-return]


# ── CSRF / origin guard ──────────────────────────────────────────────────────
# The API is unauthenticated and loopback-only, so CORS alone is NOT enough: a
# malicious web page can issue "simple" cross-origin POSTs (form-urlencoded /
# text/plain, no custom headers) which bypass CORS preflight and are executed by
# the server even though the attacker can't read the response. Browsers always
# send an `Origin` header on cross-site requests and cannot forge it, so we reject
# mutating requests whose Origin is not a trusted (loopback / Tauri) host.
# Requests without an Origin (curl, the sidecar's own scripts, etc.) pass through.
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_matches_host(origin: str, host_header: str) -> bool:
    """Same-origin fallback: the origin's host matches the Host header, so the
    request came from the very server it is addressed to (any port — the
    launchers pick a dynamic one, and a port never changes which machine the
    browser thought it was talking to)."""
    try:
        origin_host = (urlparse(origin).hostname or "").lower()
        host = (urlparse(f"//{host_header.strip()}").hostname or "").lower()
    except ValueError:
        return False
    return bool(origin_host) and origin_host == host


def _origin_is_trusted(origin: str) -> bool:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    # Tauri webview (tauri://localhost) + any loopback host. The web-deb serves
    # the SPA on a dynamic local port, so we trust the host, not a fixed origin.
    if scheme == "tauri":
        return True
    return host in ("127.0.0.1", "localhost", "tauri.localhost")


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next: Any) -> Response:
    if request.method in _MUTATING_METHODS:
        origin = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
        if (
            origin
            and not _origin_is_trusted(origin)
            and not _origin_matches_host(origin, request.headers.get("host", ""))
        ):
            logger.warning(
                "Rejected cross-origin %s %s from untrusted origin",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=403, content={"detail": "Cross-origin request not allowed"}
            )
    return await call_next(request)  # type: ignore[no-any-return]


# ── Destructive-endpoint guard ───────────────────────────────────────────────
# The generic CSRF guard above trusts *any* loopback origin. That is the right
# call for ordinary mutations — the SPA port is dynamic and the Tauri webview
# uses its own scheme — but it is too loose for the one endpoint that
# irreversibly wipes the database: a hostile page served from another local port
# (say http://localhost:9999) is a loopback origin too, so its cross-site POST
# would sail through. Destructive endpoints therefore accept only an origin the
# app was actually configured to be reached from (settings.CORS_ORIGINS) or one
# that is same-origin with the Host header — both of which the bundled SPA and
# the Tauri webview satisfy with no client-side change.
# Non-browser clients (curl, the sidecar's own scripts) send no Origin at all
# and are unaffected. A local process already running as the user could read the
# DB file directly, so it is out of scope for an HTTP defence.
_DESTRUCTIVE_PATHS = frozenset({"/api/v1/entries/reset"})

# Irreversible endpoints also get an always-on throttle. The generic limiter
# above is production-only (rate limiting a desktop user's own saves is
# harmful), which means it is *off* in the desktop default — so a wedged
# frontend loop or a runaway script could otherwise hammer a wipe endpoint.
# Keyed apart from the generic limiter's entries (raw client IPs) so the two
# windows can never interfere.
_DESTRUCTIVE_RATE_LIMIT, _DESTRUCTIVE_RATE_WINDOW = 5, 60.0


def _origin_allowed_for_destructive(origin: str, host_header: str) -> bool:
    """True when *origin* is one this deployment itself uses (see block above)."""
    if origin in settings.CORS_ORIGINS.split(","):
        return True
    if (urlparse(origin).scheme or "").lower() == "tauri":
        return True
    return _origin_matches_host(origin, host_header)


@app.middleware("http")
async def destructive_endpoint_guard(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path not in _DESTRUCTIVE_PATHS:
        return await call_next(request)  # type: ignore[no-any-return]

    client_ip = request.client.host if request.client else "unknown"
    key = f"destructive:{client_ip}"
    now = time.time()
    hits = [t for t in _rate_store.get(key, []) if now - t < _DESTRUCTIVE_RATE_WINDOW]
    if len(hits) >= _DESTRUCTIVE_RATE_LIMIT:
        retry_after = max(1, int(_DESTRUCTIVE_RATE_WINDOW - (now - hits[0])) + 1)
        logger.warning("Throttled destructive request to %s from %s", path, client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many destructive requests"},
            headers={"Retry-After": str(retry_after)},
        )
    hits.append(now)
    _rate_store[key] = hits

    # When API_TOKEN is set the shared-token gate below already requires it for
    # every /api/* call, including these — the check here is documented, not
    # duplicated.
    origin = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
    if origin and not _origin_allowed_for_destructive(origin, request.headers.get("host") or ""):
        logger.warning("Rejected destructive request to %s from origin %s", path, origin)
        return JSONResponse(
            status_code=403, content={"detail": "Cross-origin request not allowed"}
        )
    return await call_next(request)  # type: ignore[no-any-return]


# ── Host guard + optional API token (DNS-rebinding defence) ──────────────────
# The API is unauthenticated and loopback-only, so a page at http://evil.com can
# make the victim's browser talk to it: a DNS-rebinding hostname resolves to
# 127.0.0.1 and the browser dutifully sends ``Host: evil.com`` — same-origin as
# far as the attacker is concerned, and (unlike the Origin guard above) not
# blockable by CORS. Browsers cannot forge the Host header, so we only serve
# requests addressed to a host the app itself would ever be called by: the
# loopback names and the Tauri webview origin.
# The *port* is deliberately not part of the check: the launchers pick a dynamic
# port when 18765 is taken (scripts/build-web-deb.sh), and a port never changes
# which machine the browser thought it was talking to.


def _host_is_trusted(host_header: str) -> bool:
    """True when the ``Host`` header names a host this app is legitimately on."""
    try:
        hostname = (urlparse(f"//{host_header.strip()}").hostname or "").lower()
    except ValueError:
        return False
    # RFC 6761 reserves *.localhost for the loopback, and the Tauri webview's
    # origin is tauri.localhost. Everything else must be a loopback address
    # literal (any IPv4/IPv6 spelling — see config.is_loopback_host).
    return hostname == "tauri.localhost" or is_loopback_host(hostname)


@app.middleware("http")
async def host_and_token_guard(request: Request, call_next: Any) -> Response:
    # The pytest harness (conftest.py) drives the app through an ASGI transport
    # with a synthetic ``Host: test``; that harness is not a network surface, so
    # the guard is armed only for real runs (dev / packaged / server).
    if settings.APP_ENV.strip().lower() not in ("test", "testing") and not _host_is_trusted(
        request.headers.get("host") or ""
    ):
        logger.warning(
            "Rejected %s %s with untrusted Host header", request.method, request.url.path
        )
        return JSONResponse(status_code=403, content={"detail": "Untrusted Host header"})

    # Optional shared-token gate for non-loopback deployments: when API_TOKEN is
    # set, every /api/* call must carry it. Unset (the desktop default) keeps the
    # app working with no client-side configuration.
    token = settings.API_TOKEN
    if token and request.url.path.startswith("/api/"):
        auth = request.headers.get("authorization") or ""
        provided = auth[7:].strip().encode() if auth[:7].lower() == "bearer " else b""
        if not secrets.compare_digest(provided, token.encode()):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing token"})
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
app.add_exception_handler(
    DefaultSecretKeyError,
    lambda r, e: JSONResponse(status_code=400, content={"detail": str(e)}),
)


# Global exception handler for unhandled errors
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Register routers
from app.routers.ai import router as ai_router  # noqa: E402
from app.routers.backup import router as backup_router  # noqa: E402
from app.routers.box import router as box_router  # noqa: E402
from app.routers.dropbox import router as dropbox_router  # noqa: E402
from app.routers.encryption import (  # noqa: E402
    global_router as encryption_global_router,
)
from app.routers.encryption import (  # noqa: E402
    notes_router as encryption_notes_router,
)
from app.routers.encryption import (  # noqa: E402
    router as encryption_router,
)  # noqa: E402
from app.routers.entries import router as entries_router  # noqa: E402
from app.routers.export import router as export_router  # noqa: E402
from app.routers.google_drive import router as google_drive_router  # noqa: E402
from app.routers.media import router as media_router  # noqa: E402
from app.routers.notes import router as notes_router  # noqa: E402
from app.routers.onedrive import router as onedrive_router  # noqa: E402
from app.routers.prompts import router as prompts_router  # noqa: E402
from app.routers.recordings import router as recordings_router  # noqa: E402
from app.routers.reminders import router as reminders_router  # noqa: E402
from app.routers.search import router as search_router  # noqa: E402
from app.routers.settings import router as settings_router  # noqa: E402
from app.routers.sync import router as sync_router  # noqa: E402
from app.routers.system import router as system_router  # noqa: E402
from app.routers.tags import router as tags_router  # noqa: E402
from app.routers.templates import router as templates_router  # noqa: E402
from app.routers.tts import router as tts_router  # noqa: E402
from app.routers.video_notes import router as video_router  # noqa: E402

app.include_router(ai_router)
app.include_router(entries_router)
app.include_router(notes_router)
app.include_router(tags_router)
app.include_router(tts_router)
app.include_router(media_router)
app.include_router(recordings_router)
app.include_router(backup_router)
app.include_router(google_drive_router)
app.include_router(box_router)
app.include_router(onedrive_router)
app.include_router(dropbox_router)
app.include_router(prompts_router)
app.include_router(encryption_router)
app.include_router(encryption_global_router)
app.include_router(encryption_notes_router)
app.include_router(export_router)
app.include_router(reminders_router)
app.include_router(search_router)
app.include_router(sync_router)
app.include_router(templates_router)
app.include_router(video_router)
app.include_router(settings_router)
app.include_router(system_router)


# Ollama probe result cache — /health is polled by the UI and the packaged app,
# and each uncached probe is a 2s-timeout HTTP round-trip to a service that is
# often simply not running. Cached for a short TTL so a burst of health checks
# can't pile up outbound calls (a stale-by-seconds status is fine for a soft check).
_OLLAMA_PROBE_TTL_SECONDS = 30.0
_ollama_probe: tuple[float, str] = (0.0, "unknown")


async def _ollama_probe_status() -> str:
    """Return a cached-at-most-30s Ollama availability status."""
    global _ollama_probe
    now = time.time()
    checked_at, status = _ollama_probe
    if now - checked_at < _OLLAMA_PROBE_TTL_SECONDS:
        return status
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            status = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception:
        status = "unreachable"
    _ollama_probe = (now, status)
    return status


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
    checks["ollama"] = await _ollama_probe_status()

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

        from app.core.startup_checks import get_app_integrity

        ai = get_app_integrity()
        if ai.get("ran"):
            s = ai.get("summary", {})
            checks["app_integrity"] = (
                f"ok:{s.get('ok', 0)} warn:{s.get('warn', 0)} error:{s.get('error', 0)}"
            )
        else:
            checks["app_integrity"] = "not_checked"
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
        # Unknown API paths must 404, not return the SPA: an index.html body with
        # a 200 status makes clients parse HTML as JSON and hides real routing
        # mistakes (e.g. a renamed endpoint) from both the UI and tests.
        if full_path == "api" or full_path.startswith("api/"):
            raise NotFoundError("Not found")
        file_path = _FRONTEND_DIST / full_path
        target = file_path if file_path.is_file() else (_FRONTEND_DIST / "index.html")
        # Containment: reject any path that resolves outside the frontend dist
        # directory (e.g. a crafted /%2e%2e/... URL). FastAPI does not collapse
        # ".." in path params, so this is defence-in-depth against traversal.
        if not target.resolve().is_relative_to(_FRONTEND_DIST.resolve()):
            raise NotFoundError("Not found")
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
    parser.add_argument("--host", default=settings.BIND_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=settings.BIND_PORT, help="Bind port")
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
