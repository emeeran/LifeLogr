"""System diagnostics: app-integrity report.

GET returns the cached report from the last startup run (cheap, no re-run);
POST re-runs the battery live for the Diagnostics panel's "Re-check" button.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.startup_checks import check_app_integrity, get_app_integrity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Job kinds that must not be interrupted by a window close. Exports are safe to
# abort (they only write a temp file); imports, restores and backups are not.
_SHUTDOWN_BLOCKING_JOB_KINDS = frozenset({"import", "restore", "backup"})

# Renderer-error reporting is best-effort and unauthenticated by design (a crash
# must be reportable before any auth state exists), so it is strictly capped and
# deduplicated: a render loop that throws every frame must not flood the log.
_CLIENT_ERROR_WINDOW_S = 60.0
_CLIENT_ERROR_MAX_PER_WINDOW = 20
_client_error_times: deque[float] = deque()
_client_error_seen: dict[str, float] = {}


class ClientErrorReport(BaseModel):
    """A renderer error. Never carries entry or note text."""

    message: str = Field(max_length=500)
    stack: str | None = Field(default=None, max_length=4000)
    component: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=300)
    view: str | None = Field(default=None, max_length=40)
    app_version: str | None = Field(default=None, max_length=40)


@router.post("/client-errors", status_code=204)
async def report_client_error(payload: ClientErrorReport) -> Response:
    """Record a renderer error in the backend log.

    The desktop UI talks to a devtools-less webview, so a component crash or an
    unhandled rejection is otherwise completely invisible. Deliberately narrow:
    message/stack/component/url/view only. Query strings and fragments are
    stripped, and duplicates within the window are dropped.
    """
    now = time.monotonic()
    while _client_error_times and now - _client_error_times[0] > _CLIENT_ERROR_WINDOW_S:
        _client_error_times.popleft()
    for key, seen_at in list(_client_error_seen.items()):
        if now - seen_at > _CLIENT_ERROR_WINDOW_S:
            del _client_error_seen[key]

    digest = hashlib.sha256(
        (payload.message + "\x00" + (payload.stack or "")[:800]).encode()
    ).hexdigest()
    if digest in _client_error_seen:
        return Response(status_code=204)
    if len(_client_error_times) >= _CLIENT_ERROR_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many client error reports")

    _client_error_times.append(now)
    _client_error_seen[digest] = now

    location = (payload.url or "").split("?", 1)[0].split("#", 1)[0]
    logger.warning(
        "Renderer error [%s%s] %s | at %s%s",
        payload.component or "ui",
        f" ({payload.view})" if payload.view else "",
        payload.message,
        location or "unknown",
        f" | app {payload.app_version}" if payload.app_version else "",
    )
    if payload.stack:
        logger.warning("Renderer stack: %s", payload.stack[:1500])
    return Response(status_code=204)


async def _busy_state(db: AsyncSession) -> dict[str, Any]:
    """Work that a window close must not interrupt."""
    from app.core.jobs import jobs
    from app.models.backup import BackupSnapshot

    in_progress = (
        (
            await db.execute(
                select(BackupSnapshot.config_id).where(
                    BackupSnapshot.status == "in_progress"
                )
            )
        )
        .scalars()
        .all()
    )
    blocking = [
        {"id": job.id, "kind": job.kind, "phase": job.phase}
        for job in jobs.running()
        if job.kind in _SHUTDOWN_BLOCKING_JOB_KINDS
    ]
    reasons: set[str] = set()
    if in_progress:
        reasons.add("backup")
    reasons.update(job["kind"] for job in blocking)
    return {
        "busy": bool(reasons),
        "reasons": sorted(reasons),
        "backups_in_progress": len(in_progress),
        "jobs": blocking,
    }


@router.get("/shutdown-state")
async def shutdown_state(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Whether an in-flight backup/import/restore should delay app exit.

    The desktop shell polls this before tearing down the sidecar so a close
    during a backup does not truncate an upload (see the CLOSE tasks).
    """
    return await _busy_state(db)


@router.get("/integrity")
async def get_integrity() -> dict[str, Any]:
    """Cached app-integrity report from the last startup run."""
    return get_app_integrity()


@router.post("/integrity")
async def refresh_integrity() -> dict[str, Any]:
    """Re-run the integrity battery live and return the fresh report."""
    return await check_app_integrity()


@router.post("/integrity/rebuild-search-index")
async def rebuild_search_index() -> dict[str, Any]:
    """Repopulate the FTS search index, then return the refreshed integrity report."""
    from app.core.database import rebuild_search_index as do_rebuild

    await do_rebuild()
    return await check_app_integrity()


@router.get("/egress-report")
async def egress_report(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Enumerate every surface that can send data off the device.

    Privacy is LifeLogr's headline promise, so data egress must be auditable.
    Each surface reports whether it is currently active and whether using it
    sends journal content off the machine. The Privacy settings tab renders this
    verbatim — nothing leaves the device unless explicitly turned on here.
    """
    from app.models.backup import BackupConfig, BackupSchedule
    from app.services.ai_provider_service import get_active_provider

    # Cloud AI: the active provider, unless it is the local Ollama preset.
    ai_provider = await get_active_provider()
    ai_cloud = ai_provider is not None and ai_provider.preset != "ollama"
    cloud_ai = {
        "leaves_device": ai_cloud,
        "active": ai_provider is not None,
        "provider": ai_provider.name if ai_provider else "local Ollama",
        "preset": ai_provider.preset if ai_provider else "ollama",
        "note": (
            "Running any AI tool on an entry or note sends its text to this "
            "provider — it leaves your device."
            if ai_cloud
            else "AI tools run on your machine via local Ollama."
        ),
    }

    # Cloud backup: any configured provider. Whether it actually runs is governed
    # by the single active BackupSchedule (id=1).
    configs = (await db.execute(select(BackupConfig))).scalars().all()
    configured = [
        {"provider": c.provider, "label": c.label or c.provider, "leaves_device": True}
        for c in configs
    ]
    sched = (
        await db.execute(select(BackupSchedule).where(BackupSchedule.id == 1))
    ).scalar_one_or_none()
    scheduled = sched is not None and sched.config_id is not None
    cloud_backup = {
        "configured": configured,
        "scheduled": scheduled,
        "note": (
            "A scheduled cloud backup uploads an encrypted archive of your journal to the provider."
            if scheduled
            else "No cloud backup is scheduled. (Configured providers only run when you back up.)"
        ),
    }

    return {
        "cloud_ai": cloud_ai,
        "cloud_backup": cloud_backup,
        "web_clip": {
            "leaves_device": False,
            "note": "When you clip a web address, the backend fetches that page to "
            "extract its text. The URL leaves your machine; your journal data does not.",
        },
        "ocr": {
            "leaves_device": False,
            "engine": "tesseract",
            "note": "Image text recognition runs locally with Tesseract.",
        },
        # Read-aloud is a genuinely remote surface: Edge TTS is Microsoft's
        # hosted speech service (see routers/tts.py), so the text being read
        # — entry/note body or a text selection — is uploaded to it.
        "read_aloud": {
            "leaves_device": True,
            "provider": "Microsoft Edge TTS",
            "note": "Read-aloud sends the text it reads (entry, note, or selection) "
            "to Microsoft's Edge text-to-speech service to generate the audio.",
        },
        # Embeddings route through the active AI provider too, so they leave the
        # device when cloud AI is on — not just the chat tools.
        "embeddings": {
            "leaves_device": ai_cloud,
            "note": (
                "Vector embeddings are generated by the active AI provider, which "
                "is a cloud provider here."
                if ai_cloud
                else "Vector embeddings are generated locally by Ollama."
            ),
        },
        # Weather auto-fill is opt-in (off by default) and tied to location
        # data: the only payload is the rounded coordinates (~1 km) + the entry
        # date. See services/weather_service.py.
        "weather": {
            "leaves_device": bool(settings.WEATHER_ENABLED),
            "provider": "Open-Meteo",
            "note": "When enabled, saving a geotagged entry sends only the "
            "rounded coordinates (~1 km) and the entry date to Open-Meteo for "
            "daily conditions. Entry text is never sent; responses are cached "
            "on disk.",
        },
        # Map basemap tiles: plot-only by default; enabling online tiles means
        # OpenStreetMap's tile servers see the viewed area (possibly enough to
        # infer a home location). The setting is persisted so this row is live.
        "map_tiles": {
            "leaves_device": bool(settings.MAP_ONLINE_TILES),
            "provider": "OpenStreetMap",
            "note": "The map view is plot-only by default — no tile requests "
            "leave the device. When you enable online basemap tiles, the tile "
            "server sees the areas you view (which could hint at a home "
            "location).",
        },
    }
