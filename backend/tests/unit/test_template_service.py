"""TemplateService — CRUD plus the built-in protection contract.

Built-in templates are seeded at every boot (``_seed_builtin_templates``), so a
user must never be able to rename or delete one: the seeded copy would come
back on the next start anyway, and the deletion would silently fail the "my
template vanished" way. These lock that both mutations are refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.template import Template
from app.schemas.template import TemplateCreate, TemplateUpdate
from app.services.template_service import TemplateService


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, Template]:
    """One user template and one built-in, committed."""
    user = Template(name="Meeting notes", body="## Attendees\n\n", is_builtin=False)
    builtin = Template(name="Daily Reflection", body="## How I'm feeling\n\n", is_builtin=True)
    db_session.add_all([user, builtin])
    await db_session.commit()
    return {"user": user, "builtin": builtin}


class TestListAndGet:
    async def test_list_all_returns_every_template(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        templates = await svc.list_all()
        assert {t.name for t in templates} == {"Meeting notes", "Daily Reflection"}

    async def test_get_returns_the_requested_template(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        got = await svc.get(seeded["user"].id)
        assert got.id == seeded["user"].id
        assert got.body == "## Attendees\n\n"

    async def test_get_missing_raises_not_found(self, db_session: AsyncSession):
        svc = TemplateService(db_session)
        with pytest.raises(NotFoundError):
            await svc.get(99999)


class TestCreate:
    async def test_create_persists_a_user_template(self, db_session: AsyncSession):
        svc = TemplateService(db_session)
        t = await svc.create(TemplateCreate(name="Weekly Review", body="## Wins\n\n"))
        assert t.id is not None
        assert t.name == "Weekly Review"
        assert t.is_builtin is False

        reread = await svc.get(t.id)
        assert reread.name == "Weekly Review"


class TestUpdate:
    async def test_update_name_and_body(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        t = await svc.update(
            seeded["user"].id,
            TemplateUpdate(name="Renamed", body="## New body\n"),
        )
        assert t.name == "Renamed"
        assert t.body == "## New body\n"

    async def test_partial_update_keeps_untouched_field(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        t = await svc.update(seeded["user"].id, TemplateUpdate(name="Only renamed"))
        assert t.name == "Only renamed"
        assert t.body == "## Attendees\n\n"

    async def test_builtin_cannot_be_updated(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        with pytest.raises(ConflictError):
            await svc.update(seeded["builtin"].id, TemplateUpdate(name="Hacked"))

    async def test_update_missing_raises_not_found(self, db_session: AsyncSession):
        svc = TemplateService(db_session)
        with pytest.raises(NotFoundError):
            await svc.update(424242, TemplateUpdate(name="nope"))


class TestDelete:
    async def test_delete_user_template(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        await svc.delete(seeded["user"].id)
        with pytest.raises(NotFoundError):
            await svc.get(seeded["user"].id)

    async def test_builtin_cannot_be_deleted(self, db_session: AsyncSession, seeded):
        svc = TemplateService(db_session)
        with pytest.raises(ConflictError):
            await svc.delete(seeded["builtin"].id)
        # Still there afterwards.
        assert (await svc.get(seeded["builtin"].id)).id == seeded["builtin"].id
