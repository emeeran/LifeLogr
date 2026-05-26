"""Business logic for entry templates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.template import Template
from app.schemas.template import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[Template]:
        result = await self.db.execute(select(Template).order_by(Template.name))
        return list(result.scalars().all())

    async def get(self, template_id: int) -> Template:
        result = await self.db.execute(select(Template).where(Template.id == template_id))
        t = result.scalar_one_or_none()
        if not t:
            raise NotFoundError(f"Template {template_id} not found")
        return t

    async def create(self, data: TemplateCreate) -> Template:
        t = Template(name=data.name, body=data.body)
        self.db.add(t)
        await self.db.commit()
        await self.db.refresh(t)
        return t

    async def update(self, template_id: int, data: TemplateUpdate) -> Template:
        t = await self.get(template_id)
        if t.is_builtin:
            raise ConflictError("Built-in templates cannot be modified")
        if data.name is not None:
            t.name = data.name
        if data.body is not None:
            t.body = data.body
        await self.db.commit()
        await self.db.refresh(t)
        return t

    async def delete(self, template_id: int) -> None:
        t = await self.get(template_id)
        if t.is_builtin:
            raise ConflictError("Built-in templates cannot be deleted")
        await self.db.delete(t)
        await self.db.commit()
