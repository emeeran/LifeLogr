"""Export as HTML archive ZIP — attachments, gallery, collisions, date filter."""

from __future__ import annotations

import io
import zipfile

from httpx import AsyncClient

from tests.helpers.dayone_zip import PNG_1X1


async def _seed_entry_with_photo(client: AsyncClient, day: str, filename: str) -> int:
    r = await client.post(
        "/api/v1/entries", json={"entry_date": day, "body": f"Photo day {day}."}
    )
    entry_id = r.json()["id"]
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry_id), "caption": ""},
        files={"file": (filename, PNG_1X1, "image/png")},
    )
    assert r.status_code == 201, r.text
    return entry_id


def _unzip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


async def test_export_html_zip_contains_index_and_attachments(client: AsyncClient) -> None:
    await _seed_entry_with_photo(client, "2026-06-01", "ridge.png")
    r = await client.get("/api/v1/entries/export/html-zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = _unzip(r.content)
    assert "website/index.html" in zf.namelist()
    assert "attachments/2026-06-01/ridge.png" in zf.namelist()
    page = zf.read("website/index.html").decode()
    assert "Photo day 2026-06-01." in page
    # Relative reference from website/ into attachments/.
    assert '../attachments/2026-06-01/ridge.png' in page


async def test_export_html_zip_gallery_for_unreferenced_media(client: AsyncClient) -> None:
    """Media the body doesn't reference renders as a figure gallery block."""
    await _seed_entry_with_photo(client, "2026-06-02", "unreferenced.png")
    zf = _unzip((await client.get("/api/v1/entries/export/html-zip")).content)
    page = zf.read("website/index.html").decode()
    assert "<figure>" in page
    assert "unreferenced.png" in page


async def test_export_html_zip_body_referenced_media_not_duplicated(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/entries",
        json={"entry_date": "2026-06-03", "body": "Inline: /api/v1/media/1/file."},
    )
    entry_id = r.json()["id"]
    await client.post(
        "/api/v1/media",
        data={"entry_id": str(entry_id), "caption": ""},
        files={"file": ("inline.png", PNG_1X1, "image/png")},
    )
    zf = _unzip((await client.get("/api/v1/entries/export/html-zip")).content)
    page = zf.read("website/index.html").decode()
    assert "<figure>" not in page  # referenced by API URL → no gallery duplicate


async def test_export_html_zip_same_day_same_filename_no_collision(client: AsyncClient) -> None:
    """Two same-day attachments with one filename must both survive."""
    await _seed_entry_with_photo(client, "2026-06-04", "same.png")
    entries = (await client.get("/api/v1/entries")).json()
    entry_id = entries["items"][0]["id"] if isinstance(entries, dict) else entries[0]["id"]
    # Upload path already consumed one; attach the same filename to a second
    # media row on the same entry via a second entry (same date).
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-06-04", "body": "Second entry."}
    )
    second_id = r.json()["id"]
    r = await client.post(
        "/api/v1/media",
        data={"entry_id": str(second_id), "caption": ""},
        files={"file": ("same.png", PNG_1X1, "image/png")},
    )
    assert r.status_code == 201
    assert entry_id  # sanity

    zf = _unzip((await client.get("/api/v1/entries/export/html-zip")).content)
    names = zf.namelist()
    pngs = [n for n in names if n.endswith("same.png")]
    assert len(pngs) == 2  # one disambiguated with an <id>- prefix
    assert any("-" in n.split("/")[-1].removesuffix(".png") for n in pngs)


async def test_export_html_zip_date_range_filter(client: AsyncClient) -> None:
    await _seed_entry_with_photo(client, "2026-06-05", "in-range.png")
    await _seed_entry_with_photo(client, "2026-07-05", "out-of-range.png")
    r = await client.get(
        "/api/v1/entries/export/html-zip",
        params={"start_date": "2026-06-01", "end_date": "2026-06-30"},
    )
    zf = _unzip(r.content)
    names = zf.namelist()
    assert "attachments/2026-06-05/in-range.png" in names
    assert not any("out-of-range" in n for n in names)
