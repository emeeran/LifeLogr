"""Exports never include attachments of encrypted entries (SEC-MEDIA-7).

The entry body is passphrase-encrypted, so an export can never contain a
coherent decrypted document for it — and decrypting the attachment into a
plaintext export file would leak exactly the content the user hid. Media is
omitted instead (the entry itself still exports, with its ciphertext body, as
before).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

from httpx import AsyncClient

from app.models.entry import Entry
from tests.helpers.dayone_zip import PNG_1X1


async def _seed_encrypted_entry_with_photo(client: AsyncClient, db_session) -> Entry:
    entry = Entry(entry_date=date(2026, 7, 1), body="ciphertext-body", title="T")
    entry.is_encrypted = True
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry.id)},
        files={"file": ("secret.png", PNG_1X1, "image/png")},
    )
    assert r.status_code == 201, r.text
    return entry


def _names(content: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(content)).namelist()


async def test_html_zip_omits_encrypted_entry_attachments(
    client: AsyncClient, db_session
) -> None:
    entry = await _seed_encrypted_entry_with_photo(client, db_session)
    r = await client.get("/api/v1/entries/export/html-zip")
    assert r.status_code == 200
    names = _names(r.content)
    assert not any(name.startswith(f"attachments/{entry.entry_date}") for name in names)
    # Plaintext entries are unaffected — the zip itself still exports.
    assert "website/index.html" in names


async def test_markdown_zips_omit_encrypted_entry_attachments(
    client: AsyncClient, db_session
) -> None:
    entry = await _seed_encrypted_entry_with_photo(client, db_session)

    # Obsidian vault export (/api/v1/export/markdown) + frontmatter note.
    r = await client.get("/api/v1/export/markdown")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert not any(
        name.startswith(f"attachments/{entry.entry_date}") for name in zf.namelist()
    )
    page = zf.read(f"journal/2026/07/{entry.entry_date}.md").decode()
    assert "Attachments of this encrypted entry are omitted from exports." in page

    # Diarium-compatible markdown export (/api/v1/entries/export/markdown).
    r = await client.get("/api/v1/entries/export/markdown")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert not any(name.startswith("media/") for name in zf.namelist())
    assert PNG_1X1 not in r.content


async def test_diarium_export_omits_encrypted_entry_attachments(
    client: AsyncClient, db_session
) -> None:
    await _seed_encrypted_entry_with_photo(client, db_session)
    r = await client.get("/api/v1/entries/export/diarium")
    assert r.status_code == 200
    body = r.content
    # The photo bytes must not appear anywhere in the .diary payload.
    assert PNG_1X1 not in body


async def test_dayone_export_skips_encrypted_entries_entirely(
    client: AsyncClient, db_session
) -> None:
    await _seed_encrypted_entry_with_photo(client, db_session)
    r = await client.get("/api/v1/entries/export/dayone-zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    photos = [n for n in zf.namelist() if "photos" in n]
    assert photos == []
    assert PNG_1X1 not in r.content
