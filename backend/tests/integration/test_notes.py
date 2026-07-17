"""Integration tests for note sub-pages (EPIM-style page tabs)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.note import NotePage

pytestmark = pytest.mark.asyncio


async def _make_note(client: AsyncClient, **kw) -> dict:
    payload = {"title": "Note", "body": "main body", **kw}
    r = await client.post("/api/v1/notes", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_page_and_it_appears_in_note(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]

    r = await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "Tab A", "body": "a"})
    assert r.status_code == 201, r.text
    page = r.json()
    assert page["note_id"] == nid
    assert page["title"] == "Tab A"
    assert page["sort_order"] == 0

    # The note response now lists the page.
    got = (await client.get(f"/api/v1/notes/{nid}")).json()
    assert len(got["pages"]) == 1
    assert got["pages"][0]["id"] == page["id"]


async def test_update_page(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    page = (
        await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "t", "body": "b"})
    ).json()

    r = await client.patch(
        f"/api/v1/notes/{nid}/pages/{page['id']}",
        json={"title": "renamed", "body": "new body"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "renamed"
    assert r.json()["body"] == "new body"


async def test_pages_get_incrementing_sort_order(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    p1 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "1"})).json()
    p2 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "2"})).json()
    p3 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "3"})).json()
    assert (p1["sort_order"], p2["sort_order"], p3["sort_order"]) == (0, 1, 2)


async def test_reorder_pages(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    p1 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "1"})).json()
    p2 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "2"})).json()
    p3 = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "3"})).json()

    # Reverse the order.
    r = await client.post(
        f"/api/v1/notes/{nid}/pages/reorder",
        json={
            "items": [
                {"id": p3["id"], "sort_order": 0},
                {"id": p2["id"], "sort_order": 1},
                {"id": p1["id"], "sort_order": 2},
            ]
        },
    )
    assert r.status_code == 200, r.text

    got = (await client.get(f"/api/v1/notes/{nid}")).json()
    order = [p["id"] for p in got["pages"]]
    assert order == [p3["id"], p2["id"], p1["id"]]


async def test_delete_page(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    page = (await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "x"})).json()

    r = await client.delete(f"/api/v1/notes/{nid}/pages/{page['id']}")
    assert r.status_code == 204, r.text

    got = (await client.get(f"/api/v1/notes/{nid}")).json()
    assert got["pages"] == []


async def test_page_not_found_is_404(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    r = await client.patch(f"/api/v1/notes/{nid}/pages/9999", json={"title": "nope"})
    assert r.status_code == 404


async def test_pages_cascade_delete_with_note(client: AsyncClient, db_session):
    note = await _make_note(client)
    nid = note["id"]
    await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "1"})
    await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "2"})

    # ORM-delete the note: the relationship's cascade="all, delete-orphan"
    # must remove its pages too (this is the mechanism the app relies on,
    # since notes are normally soft-deleted).
    from app.models.note import Note

    n = (await db_session.execute(select(Note).where(Note.id == nid))).scalar_one()
    page_ids = [p.id for p in n.pages]
    assert len(page_ids) == 2
    await db_session.delete(n)
    await db_session.commit()

    leftover = (
        (await db_session.execute(select(NotePage).where(NotePage.id.in_(page_ids))))
        .scalars()
        .all()
    )
    assert leftover == []


async def test_soft_deleting_note_hides_its_pages(client: AsyncClient):
    note = await _make_note(client)
    nid = note["id"]
    await client.post(f"/api/v1/notes/{nid}/pages", json={"title": "1"})

    r = await client.delete(f"/api/v1/notes/{nid}")
    assert r.status_code == 204, r.text
    # The note (and therefore its pages) is no longer reachable.
    assert (await client.get(f"/api/v1/notes/{nid}")).status_code == 404
