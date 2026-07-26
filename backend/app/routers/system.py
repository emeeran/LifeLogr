"""System diagnostics: app-integrity report.

GET returns the cached report from the last startup run (cheap, no re-run);
POST re-runs the battery live for the Diagnostics panel's "Re-check" button.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.startup_checks import check_app_integrity, get_app_integrity

router = APIRouter(prefix="/api/v1/system", tags=["system"])


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
