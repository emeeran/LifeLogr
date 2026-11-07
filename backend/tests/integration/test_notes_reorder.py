"""Integration tests for note/folder batch reorder (DND-3).

Notes gain a ``sort_order`` column so the rail can keep a manual drag order;
folders already had one but could only be reordered one PATCH at a time.
"""

from httpx import AsyncClient


async def _create_folder(client: AsyncClient, name: str) -> dict:
    r = await client.post("/api/v1/notes/folders", json={"name": name})
    assert r.status_code == 201
    return r.json()


async def _create_note(client: AsyncClient, title: str, folder_id: int | None = None) -> dict:
    r = await client.post(
        "/api/v1/notes", json={"title": title, "body": f"{title} body", "folder_id": folder_id}
    )
    assert r.status_code == 201
    return r.json()


def _ids_in_order(items: list[dict]) -> list[int]:
    return [item["id"] for item in items]


class TestNotesReorder:
    async def test_reorder_sets_sort_order_and_list_order(self, client: AsyncClient):
        folder = await _create_folder(client, "Reordered")
        a = await _create_note(client, "A", folder["id"])
        b = await _create_note(client, "B", folder["id"])
        c = await _create_note(client, "C", folder["id"])

        # Drop C before A (client sends 1-based positions for the whole section)
        r = await client.post(
            "/api/v1/notes/reorder",
            json={"items": [{"id": c["id"], "sort_order": 1}, {"id": a["id"], "sort_order": 2},
                            {"id": b["id"], "sort_order": 3}]},
        )
        assert r.status_code == 200
        assert r.json()["reordered"] == 3

        r = await client.get(f"/api/v1/notes?folder_id={folder['id']}")
        assert r.status_code == 200
        assert _ids_in_order(r.json()["items"]) == [c["id"], a["id"], b["id"]]
        assert [i["sort_order"] for i in r.json()["items"]] == [1, 2, 3]

    async def test_unfiled_section_reorders(self, client: AsyncClient):
        a = await _create_note(client, "U1")
        b = await _create_note(client, "U2")
        r = await client.post(
            "/api/v1/notes/reorder",
            json={"items": [{"id": b["id"], "sort_order": 1}, {"id": a["id"], "sort_order": 2}]},
        )
        assert r.status_code == 200
        r = await client.get("/api/v1/notes")
        assert _ids_in_order(r.json()["items"]) == [b["id"], a["id"]]

    async def test_reorder_unknown_note_404(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/notes/reorder",
            json={"items": [{"id": 424242, "sort_order": 1}]},
        )
        assert r.status_code == 404

    async def test_reorder_rejects_negative_sort_order(self, client: AsyncClient):
        note = await _create_note(client, "Neg")
        r = await client.post(
            "/api/v1/notes/reorder",
            json={"items": [{"id": note["id"], "sort_order": -1}]},
        )
        assert r.status_code == 422

    async def test_default_order_unchanged_without_reorder(self, client: AsyncClient):
        """Sections never reordered keep the pinned/recent ordering (all sort_order 0)."""
        folder = await _create_folder(client, "Untouched")
        first = await _create_note(client, "First", folder["id"])
        second = await _create_note(client, "Second", folder["id"])
        r = await client.get(f"/api/v1/notes?folder_id={folder['id']}")
        assert _ids_in_order(r.json()["items"]) == [second["id"], first["id"]]

    async def test_new_note_appends_to_manually_ordered_section(self, client: AsyncClient):
        """A section with a manual order (sort_order >= 1 in use) files new notes at the end."""
        folder = await _create_folder(client, "Manual")
        a = await _create_note(client, "A", folder["id"])
        b = await _create_note(client, "B", folder["id"])
        await client.post(
            "/api/v1/notes/reorder",
            json={"items": [{"id": b["id"], "sort_order": 1}, {"id": a["id"], "sort_order": 2}]},
        )
        fresh = await _create_note(client, "Fresh", folder["id"])
        assert fresh["sort_order"] == 3
        r = await client.get(f"/api/v1/notes?folder_id={folder['id']}")
        assert _ids_in_order(r.json()["items"]) == [b["id"], a["id"], fresh["id"]]

    async def test_new_note_tops_untouched_section(self, client: AsyncClient):
        """Default (all-zero) sections keep recent-first: a new note has sort_order 0."""
        folder = await _create_folder(client, "Auto")
        old = await _create_note(client, "Old", folder["id"])
        fresh = await _create_note(client, "Fresh", folder["id"])
        assert fresh["sort_order"] == 0
        r = await client.get(f"/api/v1/notes?folder_id={folder['id']}")
        assert _ids_in_order(r.json()["items"]) == [fresh["id"], old["id"]]


class TestFoldersReorder:
    async def test_folder_reorder_batch(self, client: AsyncClient):
        f1 = await _create_folder(client, "One")
        f2 = await _create_folder(client, "Two")
        f3 = await _create_folder(client, "Three")
        r = await client.post(
            "/api/v1/notes/folders/reorder",
            json={"items": [{"id": f3["id"], "sort_order": 1}, {"id": f1["id"], "sort_order": 2},
                            {"id": f2["id"], "sort_order": 3}]},
        )
        assert r.status_code == 200
        assert r.json()["reordered"] == 3
        r = await client.get("/api/v1/notes/folders")
        assert [f["id"] for f in r.json()] == [f3["id"], f1["id"], f2["id"]]

    async def test_folder_reorder_unknown_404(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/notes/folders/reorder",
            json={"items": [{"id": 424242, "sort_order": 1}]},
        )
        assert r.status_code == 404
