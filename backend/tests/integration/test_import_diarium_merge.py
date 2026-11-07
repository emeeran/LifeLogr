"""Idempotent Diarium ``.diary`` merge — identity, media backfill, conflicts.

A ``.diary`` pull is the only attachment-complete path out of Diarium, so it has
to be safe to repeat: re-importing a newer backup must update what the source
changed, restore attachments that went missing, and never fork the journal into
duplicates.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.entry import Entry
from app.models.media import Media
from app.services.importers import parse_diarium_sqlite
from tests.helpers.diarium_diary import build_diary, ticks_for

# Minimal blobs are fine: the importer only checks magic bytes + size.
PHOTO = b"\xff\xd8\xff\xe0merge-photo-a"
PHOTO_B = b"\xff\xd8\xff\xe0merge-photo-b"


def _diary(entries: list[dict], *, media: bool = True) -> bytes:
    return build_diary(entries, include_media=media)


async def _import(client: AsyncClient, data: bytes, **params):
    return await client.post(
        "/api/v1/entries/import/file",
        params=params or None,
        files={"file": ("Diarium.diary", data, "application/octet-stream")},
    )


def _media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "MEDIA_DIR", root)
    return root


def test_parse_diarium_sqlite_preserves_identity_and_heading_only_entries() -> None:
    """Regression: identity is carried through, and a heading with no body is content."""
    parsed = parse_diarium_sqlite(
        _diary(
            [
                {"date": "2026-03-01", "heading": "Trip", "text": "<p>Went hiking.</p>"},
                {"date": "2025-06-28", "heading": "MEGAMALAI TRIP", "text": ""},
            ],
            media=False,
        )
    )
    # Parsed in tick order (oldest first).
    assert {p["external_id"] for p in parsed} == {
        str(ticks_for("2026-03-01")),
        str(ticks_for("2025-06-28")),
    }
    assert {p["external_source"] for p in parsed} == {"diarium"}
    # The heading-only entry survives instead of being dropped as empty noise.
    heading_only = next(p for p in parsed if p["external_id"] == str(ticks_for("2025-06-28")))
    assert heading_only["title"] == "MEGAMALAI TRIP"
    assert heading_only["body"] == ""


async def test_diary_reimport_is_idempotent(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    diary = _diary(
        [
            {
                "date": "2026-03-01",
                "heading": "Trip",
                "text": "<p>Went hiking.</p>",
                "media": [("IMG_1", ".jpg", PHOTO)],
            }
        ]
    )

    first = await _import(client, diary)
    assert first.status_code == 200
    assert first.json()["imported"] == 1, first.text

    second = (await _import(client, diary)).json()
    assert second["imported"] == 0
    assert second["updated"] == 0
    assert second["media_backfilled"] == 0
    assert second["conflicts"] == 0

    rows = (await db_session.execute(select(Entry))).scalars().all()
    assert len(rows) == 1
    assert rows[0].external_source == "diarium"
    assert rows[0].external_id == str(ticks_for("2026-03-01"))
    assert rows[0].sync_hash is not None

    media = (await db_session.execute(select(Media))).scalars().all()
    assert len(media) == 1


async def test_reimport_restores_only_the_missing_attachment(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    """A partially lost entry is repaired, and the surviving file is not duplicated."""
    root = _media_root(tmp_path, monkeypatch)
    diary = _diary(
        [
            {
                "date": "2026-04-02",
                "heading": "Two photos",
                "text": "<p>Both.</p>",
                "media": [("A", ".jpg", PHOTO), ("B", ".jpg", PHOTO_B)],
            }
        ]
    )
    assert (await _import(client, diary)).json()["imported"] == 1

    media = (await db_session.execute(select(Media).order_by(Media.id))).scalars().all()
    assert len(media) == 2
    victim = media[1]
    (root / victim.storage_path).unlink()
    await db_session.delete(victim)
    await db_session.commit()

    second = (await _import(client, diary)).json()
    assert second["imported"] == 0
    assert second["media_backfilled"] == 1, second

    media = (await db_session.execute(select(Media).order_by(Media.id))).scalars().all()
    assert len(media) == 2
    assert len({m.storage_path for m in media}) == 2
    assert all((root / m.storage_path).is_file() for m in media)


async def test_source_edit_updates_a_locally_untouched_entry(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    _media_root(tmp_path, monkeypatch)
    first = _diary([{"date": "2026-05-04", "text": "<p>first draft</p>"}], media=False)
    revised = _diary([{"date": "2026-05-04", "text": "<p>second draft</p>"}], media=False)

    assert (await _import(client, first)).json()["imported"] == 1
    updated = (await _import(client, revised)).json()
    assert updated["imported"] == 0
    assert updated["updated"] == 1, updated
    assert updated["conflicts"] == 0

    row = (await db_session.execute(select(Entry))).scalar_one()
    assert row.body == "second draft"


async def test_local_edit_wins_and_is_reported_as_conflict(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    """Ambiguity never overwrites LifeLogr text: the pull reports a conflict."""
    _media_root(tmp_path, monkeypatch)
    diary = _diary([{"date": "2026-06-05", "text": "<p>source words</p>"}], media=False)
    assert (await _import(client, diary)).json()["imported"] == 1

    row = (await db_session.execute(select(Entry))).scalar_one()
    row.body = "my own words, written in LifeLogr"
    await db_session.commit()

    result = (await _import(client, diary)).json()
    assert result["updated"] == 0
    assert result["conflicts"] == 1, result
    assert any("conflict" in r["reason"] for r in result["skip_reasons"])

    refreshed = await db_session.get(Entry, row.id)
    assert refreshed.body == "my own words, written in LifeLogr"


async def test_adoption_fills_missing_geo_without_a_permanent_conflict(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    """Pre-identity rows gain the source's geo, and the pull stays quiet after that.

    Regression: the fingerprint covers latitude/longitude, so adopting a row
    without copying the source's coordinates made every later pull report the
    same entry as a conflict forever.
    """
    from datetime import date as date_type

    _media_root(tmp_path, monkeypatch)
    legacy = Entry(entry_date=date_type(2024, 9, 9), body="Same words.", mood=None)
    db_session.add(legacy)
    await db_session.commit()

    diary = _diary(
        [
            {
                "date": "2024-09-09",
                "text": "<p>Same words.</p>",
                "lat": 25.6,
                "lon": 91.9,
            }
        ],
        media=False,
    )

    first = (await _import(client, diary)).json()
    assert first["imported"] == 0
    assert first["conflicts"] == 0, first

    row = (await db_session.execute(select(Entry))).scalar_one()
    assert row.external_id == str(ticks_for("2024-09-09"))
    assert row.latitude == 25.6 and row.longitude == 91.9

    second = (await _import(client, diary)).json()
    assert second["conflicts"] == 0, second
    assert second["updated"] == 0


async def test_append_mode_still_duplicates(
    client: AsyncClient, db_session, tmp_path, monkeypatch
) -> None:
    """Escape hatch: mode=append preserves the pre-merge always-insert behaviour."""
    _media_root(tmp_path, monkeypatch)
    diary = _diary([{"date": "2026-07-06", "text": "<p>twice</p>"}], media=False)

    assert (await _import(client, diary)).json()["imported"] == 1
    appended = (await _import(client, diary, mode="append")).json()
    assert appended["imported"] == 1

    rows = (await db_session.execute(select(Entry))).scalars().all()
    assert len(rows) == 2
    # The merge import claimed the source's id; the appended copy records none,
    # which is what keeps the unique index satisfiable.
    assert sum(1 for r in rows if r.external_id == str(ticks_for("2026-07-06"))) == 1
    assert sum(1 for r in rows if r.external_id is None) == 1
