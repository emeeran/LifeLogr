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


@pytest.mark.asyncio
async def test_export_single_markdown_round_trip(db_session):
    svc = NoteService(db_session)
    note = await svc.create(NoteCreate(title="My Note", body="hello **world**"))
    exp = NotesExportService(db_session)

    res = await exp.export_single_markdown(note.id)
    assert res is not None
    filename, content = res
    assert filename.endswith(".md")
    text = content.decode()
    assert "My Note" in text  # title in frontmatter
    assert "hello **world**" in text  # body verbatim — markdown is lossless

    # Re-importing the exported bytes creates a NEW note with the body restored.
    out = await exp.import_single_markdown(content)
    assert out["imported"] == 1 and out["skipped"] == 0
    assert out["note_id"] is not None and out["note_id"] != note.id
    imported = await svc.get(out["note_id"])
    assert imported.body == "hello **world**"


@pytest.mark.asyncio
async def test_export_single_markdown_missing_note(db_session):
    res = await NotesExportService(db_session).export_single_markdown(999999)
    assert res is None


@pytest.mark.asyncio
async def test_import_single_markdown_returns_note_id(db_session):
    md = b"---\ntitle: Imported\ntags: [a, b]\npinned: true\n---\nbody text"
    out = await NotesExportService(db_session).import_single_markdown(md)
    assert out["imported"] == 1 and out["note_id"] is not None
    note = await NoteService(db_session).get(out["note_id"])
    assert note.title == "Imported"
    assert note.is_pinned is True
    # Frontmatter tags are embedded as #tokens (tags live in the text).
    assert note.body.startswith("body text")
    assert "#a" in note.body and "#b" in note.body
