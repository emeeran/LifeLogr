"""API endpoints for entry templates."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.template import TemplateCreate, TemplateResponse, TemplateUpdate
from app.services.template_service import TemplateService

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)) -> Any:
    svc = TemplateService(db)
    return await svc.list_all()


@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template(data: TemplateCreate, db: AsyncSession = Depends(get_db)) -> Any:
    svc = TemplateService(db)
    return await svc.create(data)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int, data: TemplateUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = TemplateService(db)
    return await svc.update(template_id, data)


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = TemplateService(db)
    await svc.delete(template_id)
