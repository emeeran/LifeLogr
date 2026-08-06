"""NoteFolder nesting: sub-folders, re-parenting, and the acyclic guard."""

from __future__ import annotations

import pytest

from app.schemas.note import NoteFolderCreate, NoteFolderUpdate
from app.services.note_service import NoteService


@pytest.mark.asyncio
async def test_create_subfolder_and_list(db_session):
    svc = NoteService(db_session)
    parent = await svc.create_folder(NoteFolderCreate(name="Parent"))
    child = await svc.create_folder(NoteFolderCreate(name="Child", parent_id=parent.id))

    folders = {f.id: f for f, _ in await svc.list_folders()}
    assert folders[child.id].parent_id == parent.id
    assert folders[parent.id].parent_id is None


@pytest.mark.asyncio
async def test_reparent_and_clear_parent(db_session):
    svc = NoteService(db_session)
    a = await svc.create_folder(NoteFolderCreate(name="A"))
    b = await svc.create_folder(NoteFolderCreate(name="B"))

    await svc.update_folder(b.id, NoteFolderUpdate(parent_id=a.id))
    folders = {f.id: f for f, _ in await svc.list_folders()}
    assert folders[b.id].parent_id == a.id

    await svc.update_folder(b.id, NoteFolderUpdate(clear_parent=True))
    folders = {f.id: f for f, _ in await svc.list_folders()}
    assert folders[b.id].parent_id is None


@pytest.mark.asyncio
async def test_cycle_guard_prevents_moving_into_descendant(db_session):
    svc = NoteService(db_session)
    a = await svc.create_folder(NoteFolderCreate(name="A"))
    b = await svc.create_folder(NoteFolderCreate(name="B", parent_id=a.id))
    c = await svc.create_folder(NoteFolderCreate(name="C", parent_id=b.id))

    # Moving A under C (its own descendant) is refused — A stays at top level.
    await svc.update_folder(a.id, NoteFolderUpdate(parent_id=c.id))
    folders = {f.id: f for f, _ in await svc.list_folders()}
    assert folders[a.id].parent_id is None
    # Self-parent is also refused.
    await svc.update_folder(a.id, NoteFolderUpdate(parent_id=a.id))
    folders = {f.id: f for f, _ in await svc.list_folders()}
    assert folders[a.id].parent_id is None
