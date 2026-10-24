"""Export route handlers — PDF and HTML export."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.export_service import ExportService

router = APIRouter(prefix="/api/v1/export", tags=["export"])

# The exported document embeds user-supplied entry bodies. Even though the
# renderer escapes raw HTML, belt-and-braces: send it as a download (never
# rendered inline in the app origin) inside a sandboxed CSP that blocks script,
# form, and same-origin access.
_EXPORT_HTML_HEADERS = {
    "Content-Disposition": "attachment; filename=lifelogr-export.html",
    "Content-Security-Policy": "sandbox",
}


@router.get("/html", response_class=HTMLResponse)
async def export_html(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as a styled HTML document (downloaded, sandboxed)."""
    svc = ExportService(db)
    html = await svc.export_html(start_date, end_date)
    return HTMLResponse(content=html, headers=_EXPORT_HTML_HEADERS)


@router.get("/pdf")
async def export_pdf(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export entries as a PDF document."""
    svc = ExportService(db)
    pdf_bytes = await svc.export_pdf(start_date, end_date)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=lifelogr-export.pdf"},
    )


@router.get("/markdown")
async def export_markdown(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export entries as an Obsidian-compatible Markdown ZIP vault."""
    svc = ExportService(db)
    zip_bytes = await svc.export_markdown(start_date, end_date)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=lifelogr-obsidian-vault.zip"},
    )
