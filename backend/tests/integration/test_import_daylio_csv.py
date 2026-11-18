"""End-to-end Daylio CSV import — golden fixture, dedup, and round-trip."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.entry import Entry
from app.models.tag import EntryTag, Tag

GOLDEN = Path(__file__).parent.parent / "golden" / "daylio_export.csv"


def _csv_file() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("daylio_export.csv", GOLDEN.read_bytes(), "text/csv")}


async def test_import_daylio_csv_end_to_end(client: AsyncClient, db_session) -> None:
    r = await client.post("/api/v1/entries/import/file", files=_csv_file())
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 3, body["skip_reasons"]

    rows = (
        (await db_session.execute(select(Entry).order_by(Entry.entry_date)))
        .scalars()
        .all()
    )
    assert [str(e.entry_date) for e in rows] == ["2021-05-01", "2021-05-02", "2021-05-03"]

    first, checkin, third = rows
    # Full row: human-readable date, title from note_title, tags from activities.
    assert first.title == "Slow morning"
    assert first.mood == "good"
    tag_names = set(
        (
            await db_session.execute(
                select(Tag.name).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == first.id)
            )
        ).scalars()
    )
    assert tag_names == {"Coffee", "Gym", "Reading"}

    # Mood-only check-in survives with an empty body.
    assert checkin.body == ""
    assert checkin.mood == "great"  # rad → great
    assert "Hiking" in {
        t for (t,) in (
            await db_session.execute(
                select(Tag.name).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == checkin.id)
            )
        ).all()
    }

    assert third.mood == "awful"
    assert third.body == "Rough day at work."


async def test_import_daylio_csv_same_day_two_moods_both_survive(client: AsyncClient, db_session) -> None:
    """The dedup fix: mood-only check-ins differ by mood, not just by body."""
    csv_text = (
        "full_date,date,weekday,time,mood,activities,note_title,note\n"
        '"May 1, 2021",2021-05-01,Saturday,08:00,good,,"Coffee",\n'
        '"May 1, 2021",2021-05-01,Saturday,09:00,awful,,"Slump",\n'
    )
    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("daylio.csv", csv_text.encode(), "text/csv")},
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 2

    moods = (
        (
            await db_session.execute(
                select(Entry.mood).where(Entry.entry_date == "2021-05-01").order_by(Entry.mood)
            )
        )
        .scalars()
        .all()
    )
    assert moods == ["awful", "good"]


async def test_import_daylio_csv_identical_note_is_duplicate(client: AsyncClient, db_session) -> None:
    csv_text = (
        "full_date,date,weekday,time,mood,activities,note_title,note\n"
        '"May 1, 2021",2021-05-01,Saturday,08:00,good,,,Same note\n'
        '"May 1, 2021",2021-05-01,Saturday,08:00,good,,,Same note\n'
    )
    r = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("daylio.csv", csv_text.encode(), "text/csv")},
    )
    assert r.json()["imported"] == 1
    assert r.json()["skipped"] == 1


async def test_export_daylio_csv_round_trip_with_aliases(client: AsyncClient, db_session) -> None:
    """Import → export → import keeps counts and moods stable (rad ⇄ great)."""
    r = await client.post("/api/v1/entries/import/file", files=_csv_file())
    assert r.json()["imported"] == 3

    exported = await client.get("/api/v1/entries/export/daylio-csv")
    assert exported.status_code == 200

    r2 = await client.post(
        "/api/v1/entries/import/file",
        files={"file": ("again.csv", exported.content, "text/csv")},
    )
    # Everything dedups on the second pass — nothing imported twice.
    assert r2.json()["imported"] == 0, r2.json()["skip_reasons"]
    total = (await db_session.execute(select(func.count()).select_from(Entry))).scalar_one()
    assert total == 3
    moods = (await db_session.execute(select(Entry.mood).order_by(Entry.entry_date))).scalars().all()
    assert moods == ["good", "great", "awful"]
