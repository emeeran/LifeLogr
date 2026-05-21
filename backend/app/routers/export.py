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


@router.get("/html", response_class=HTMLResponse)
async def export_html(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export entries as a styled HTML document."""
    svc = ExportService(db)
    html = await svc.export_html(start_date, end_date)
    return HTMLResponse(content=html)


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
        headers={"Content-Disposition": "attachment; filename=diarilinux-export.pdf"},
    )
