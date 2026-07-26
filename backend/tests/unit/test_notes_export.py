"""Notes import/export: round-trip + encryption-safety."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.note import Note
from app.schemas.note import NoteCreate
from app.services.note_service import NoteService
from app.services.notes_export_service import NotesExportService


@pytest.mark.asyncio
async def test_notes_json_round_trip(db_session):
    svc = NoteService(db_session)
    await svc.create(NoteCreate(title="Shopping", body="milk & eggs"))
    exp = NotesExportService(db_session)

    raw = await exp.export_json()
    assert b"Shopping" in raw and b"milk & eggs" in raw

    res = await exp.import_json(raw)
    assert res["imported"] == 1
    notes = (await db_session.execute(select(Note))).scalars().all()
    assert len(notes) == 2  # original + imported copy


@pytest.mark.asyncio
async def test_notes_markdown_zip_round_trip(db_session):
    await NoteService(db_session).create(NoteCreate(title="Ideas", body="ship it"))
    exp = NotesExportService(db_session)
    raw = await exp.export_markdown()
    assert raw[:2] == b"PK"  # zip magic
    res = await exp.import_markdown_zip(raw)
    assert res["imported"] == 1


@pytest.mark.asyncio
async def test_encrypted_note_body_not_exported(db_session):
    db_session.add(Note(title="Secret", body="super-secret-ciphertext", is_encrypted=True))
    await db_session.commit()
    raw = await NotesExportService(db_session).export_json()
    assert b"super-secret-ciphertext" not in raw
    assert b"[encrypted" in raw
