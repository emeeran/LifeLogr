"""Integration tests for the Notes feature.

Covers note CRUD, folders, tags, pin/ordering, search (ILIKE fallback in the
trigger-less test DB), note encryption, global-search union, backup counts,
and that the note tables are auto-created.
"""

import httpx
import respx
from httpx import AsyncClient


async def _create_note(client: AsyncClient, title="My note", body="Some content", **kw):
    payload = {"title": title, "body": body, **kw}
    r = await client.post("/api/v1/notes", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestNoteCRUD:
    async def test_create_and_get(self, client: AsyncClient):
        note = await _create_note(client, title="Idea", body="Ship it")
        assert note["title"] == "Idea"
        assert note["body"] == "Ship it"
        assert note["is_pinned"] is False
        r = await client.get(f"/api/v1/notes/{note['id']}")
        assert r.status_code == 200
        assert r.json()["body"] == "Ship it"

    async def test_get_missing_returns_404(self, client: AsyncClient):
        assert (await client.get("/api/v1/notes/9999")).status_code == 404

    async def test_update_body_and_title(self, client: AsyncClient):
        note = await _create_note(client)
        r = await client.patch(
            f"/api/v1/notes/{note['id']}", json={"title": "New", "body": "Updated"}
        )
        assert r.status_code == 200
        j = r.json()
        assert j["title"] == "New"
        assert j["body"] == "Updated"

    async def test_soft_delete_and_restore(self, client: AsyncClient):
        note = await _create_note(client)
        assert (await client.delete(f"/api/v1/notes/{note['id']}")).status_code == 204
        # Soft-deleted note is hidden from normal GET
        assert (await client.get(f"/api/v1/notes/{note['id']}")).status_code == 404
        r = await client.post(f"/api/v1/notes/{note['id']}/restore")
        assert r.status_code == 200
        # Restored note is visible again via normal GET
        assert (await client.get(f"/api/v1/notes/{note['id']}")).status_code == 200


class TestNoteTags:
    async def test_assign_and_swap_tags(self, client: AsyncClient):
        t1 = (await client.post("/api/v1/tags", json={"name": "work"})).json()
        t2 = (await client.post("/api/v1/tags", json={"name": "home"})).json()
        note = await _create_note(client, tag_ids=[t1["id"]])
        assert [t["name"] for t in note["tags"]] == ["work"]
        r = await client.patch(f"/api/v1/notes/{note['id']}", json={"tag_ids": [t2["id"]]})
        assert [t["name"] for t in r.json()["tags"]] == ["home"]

    async def test_list_filter_by_tag(self, client: AsyncClient):
        t = (await client.post("/api/v1/tags", json={"name": "important"})).json()
        await _create_note(client, body="tagged", tag_ids=[t["id"]])
        await _create_note(client, body="untagged")
        r = await client.get(f"/api/v1/notes?tag_ids={t['id']}")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["body_snippet"] == "tagged"


class TestNotePin:
    async def test_pin_toggles_and_orders_first(self, client: AsyncClient):
        await _create_note(client, title="A")
        b = await _create_note(client, title="B")
        r = await client.patch(f"/api/v1/notes/{b['id']}/pin", json={"is_pinned": True})
        assert r.json()["is_pinned"] is True
        titles = [n["title"] for n in (await client.get("/api/v1/notes")).json()["items"]]
        assert titles[0] == "B"  # pinned first
        assert "A" in titles


class TestNoteFolders:
    async def test_folder_crud_and_assign(self, client: AsyncClient):
        folder = (await client.post("/api/v1/notes/folders", json={"name": "Research"})).json()
        assert folder["name"] == "Research"
        note = await _create_note(client)
        await client.patch(f"/api/v1/notes/{note['id']}", json={"folder_id": folder["id"]})
        assert (await client.get(f"/api/v1/notes/{note['id']}")).json()["folder_id"] == folder["id"]
        # Folder list reflects the live count
        folders = (await client.get("/api/v1/notes/folders")).json()
        assert folders[0]["note_count"] == 1
        # Un-file via clear_folder
        await client.patch(f"/api/v1/notes/{note['id']}", json={"clear_folder": True})
        assert (await client.get(f"/api/v1/notes/{note['id']}")).json()["folder_id"] is None
        # Soft-delete the folder
        assert (await client.delete(f"/api/v1/notes/folders/{folder['id']}")).status_code == 204


class TestNoteSearch:
    async def test_notes_search_ilike_fallback(self, client: AsyncClient):
        """The test DB has no FTS sync triggers → NoteService.search falls back to ILIKE."""
        await _create_note(client, title="Recipe", body="Mix flour and sugar")
        await _create_note(client, body="Nothing relevant here")
        r = await client.get("/api/v1/notes/search?q=flour")
        items = r.json()["items"]
        assert len(items) == 1
        assert "flour" in items[0]["body_snippet"]


class TestNoteEncryption:
    async def test_encrypt_decrypt_note(self, client: AsyncClient):
        note = await _create_note(client, title="Secret", body="Top secret content")
        r = await client.post(
            f"/api/v1/notes/{note['id']}/encryption/encrypt", json={"passphrase": "pw123"}
        )
        assert r.status_code == 200
        assert r.json()["is_encrypted"] is True
        # Body is now ciphertext, title stays readable
        after = (await client.get(f"/api/v1/notes/{note['id']}")).json()
        assert after["body"] != "Top secret content"
        assert after["title"] == "Secret"
        # Decrypt restores plaintext
        r = await client.post(
            f"/api/v1/notes/{note['id']}/encryption/decrypt", json={"passphrase": "pw123"}
        )
        assert r.json()["is_encrypted"] is False
        assert (await client.get(f"/api/v1/notes/{note['id']}")).json()[
            "body"
        ] == "Top secret content"

    async def test_encrypt_already_encrypted_errors(self, client: AsyncClient):
        note = await _create_note(client, body="x")
        await client.post(
            f"/api/v1/notes/{note['id']}/encryption/encrypt", json={"passphrase": "pw"}
        )
        r = await client.post(
            f"/api/v1/notes/{note['id']}/encryption/encrypt", json={"passphrase": "pw"}
        )
        assert r.status_code >= 400


class TestGlobalSearchUnion:
    async def test_note_appears_in_global_search(self, client: AsyncClient):
        await _create_note(client, title="UniqueNoteToken", body="findme notes content")
        r = await client.get("/api/v1/search?q=findme&mode=keyword")
        items = r.json()["items"]
        note_hits = [i for i in items if i["type"] == "note"]
        assert len(note_hits) == 1
        assert note_hits[0]["entry_date"] is None


class TestBackupCountAndTables:
    async def test_count_all_includes_notes(self, db_session):
        from app.services.backup_service import BackupService

        counts = await BackupService(db_session).count_all()
        assert "notes" in counts

    async def test_note_tables_auto_created(self, db_session):
        from sqlalchemy import text

        for table in ("notes", "note_folders", "note_tags"):
            row = (
                await db_session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                    {"n": table},
                )
            ).scalar()
            assert row == table


# 1x1 transparent PNG (valid; PIL/WebP path can open it).
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestNoteMedia:
    async def test_upload_serve_list_delete(self, client: AsyncClient):
        note = await _create_note(client, body="before image")
        r = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("pixel.png", _PNG_1x1, "image/png")},
        )
        assert r.status_code == 201, r.text
        media = r.json()
        assert media["note_id"] == note["id"]
        assert media["media_type"] == "image"
        mid = media["id"]

        # Serve the file
        r = await client.get(f"/api/v1/notes/{note['id']}/media/{mid}/file")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")

        # List includes it
        listed = (await client.get(f"/api/v1/notes/{note['id']}/media")).json()
        assert any(m["id"] == mid for m in listed)

        # Delete removes it (serve then 404s)
        assert (await client.delete(f"/api/v1/notes/{note['id']}/media/{mid}")).status_code == 204
        assert (await client.get(f"/api/v1/notes/{note['id']}/media/{mid}/file")).status_code == 404

    async def test_reject_blocked_type(self, client: AsyncClient):
        note = await _create_note(client)
        # HTML document signature is blocked by the shared media policy.
        r = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("bad.html", b"<!DOCTYPE html>x", "text/html")},
        )
        assert r.status_code == 400


class TestNoteMediaFromPath:
    async def test_import_from_path(self, client: AsyncClient, tmp_path):
        note = await _create_note(client)
        f = tmp_path / "pic.png"
        f.write_bytes(_PNG_1x1)
        r = await client.post(
            f"/api/v1/notes/{note['id']}/media/from-path",
            json={"path": str(f)},
        )
        assert r.status_code == 201, r.text
        assert r.json()["media_type"] == "image"

    async def test_missing_path_returns_404(self, client: AsyncClient):
        note = await _create_note(client)
        r = await client.post(
            f"/api/v1/notes/{note['id']}/media/from-path",
            json={"path": "/nonexistent/file.png"},
        )
        assert r.status_code == 404


# Minimal PDF body — not a blocked magic number, uploads as media_type "document".
_PDF_STUB = b"%PDF-1.4\n% not a real pdf, just enough to classify as document"


class TestNoteMediaOcr:
    """OCR endpoint for note images — mirrors the entry-media OCR endpoint.

    Per the clipping design, the endpoint only *returns* the recognized text;
    the frontend inserts it into the note body (autosave then PATCHes, which
    makes it searchable). These tests mock the OCR call so they don't depend
    on the tesseract binary being present (see test_ocr_service for real OCR).
    """

    async def test_ocr_returns_recognized_text(self, client: AsyncClient, monkeypatch):
        seen: dict[str, bytes] = {}

        def fake_ocr(data: bytes) -> str:
            seen["bytes"] = data
            return "  hello world  "

        monkeypatch.setattr("app.routers.notes.ocr_image_bytes", fake_ocr)

        note = await _create_note(client, body="before")
        up = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("pixel.png", _PNG_1x1, "image/png")},
        )
        assert up.status_code == 201, up.text
        mid = up.json()["id"]

        r = await client.post(f"/api/v1/notes/{note['id']}/media/{mid}/ocr")
        assert r.status_code == 200, r.text
        assert r.json() == {"text": "hello world"}  # leading/trailing whitespace stripped
        assert seen["bytes"] == _PNG_1x1  # the actual stored file bytes were OCRed

    async def test_ocr_text_inserted_into_body_is_searchable(
        self, client: AsyncClient, monkeypatch
    ):
        # In the trigger-less test DB, search falls back to ILIKE on body/title,
        # so inserting the OCR text into the body is what makes it findable.
        monkeypatch.setattr(
            "app.routers.notes.ocr_image_bytes", lambda data: "QuantumWidget gizmo"
        )
        note = await _create_note(client, body="snip note")
        up = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("pixel.png", _PNG_1x1, "image/png")},
        )
        mid = up.json()["id"]

        text = (
            await client.post(f"/api/v1/notes/{note['id']}/media/{mid}/ocr")
        ).json()["text"]
        # Frontend inserts OCR text into the body, then autosave PATCHes.
        await client.patch(
            f"/api/v1/notes/{note['id']}", json={"body": f"snip note\n\n{text}"}
        )

        found = (
            await client.get("/api/v1/notes/search", params={"q": "quantumwidget"})
        ).json()
        assert any(n["id"] == note["id"] for n in found["items"])

    async def test_ocr_rejects_non_image(self, client: AsyncClient):
        note = await _create_note(client)
        up = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("doc.pdf", _PDF_STUB, "application/pdf")},
        )
        assert up.status_code == 201, up.text
        mid = up.json()["id"]

        r = await client.post(f"/api/v1/notes/{note['id']}/media/{mid}/ocr")
        assert r.status_code == 400

    async def test_ocr_missing_binary_returns_500_with_hint(
        self, client: AsyncClient, monkeypatch
    ):
        def boom(data: bytes) -> str:
            raise FileNotFoundError("tesseract not found")

        monkeypatch.setattr("app.routers.notes.ocr_image_bytes", boom)
        note = await _create_note(client)
        up = await client.post(
            f"/api/v1/notes/{note['id']}/media",
            files={"file": ("pixel.png", _PNG_1x1, "image/png")},
        )
        mid = up.json()["id"]

        r = await client.post(f"/api/v1/notes/{note['id']}/media/{mid}/ocr")
        assert r.status_code == 500
        assert "tesseract" in r.json()["detail"].lower()

    async def test_ocr_missing_media_returns_404(self, client: AsyncClient):
        note = await _create_note(client)
        r = await client.post(f"/api/v1/notes/{note['id']}/media/9999/ocr")
        assert r.status_code == 404


class TestNoteWebClip:
    """Web-page → markdown fallback (desktop primary path is image capture)."""

    async def test_extracts_markdown(self, client: AsyncClient, monkeypatch):
        # Avoid real DNS in the test: example.com is treated as public.
        monkeypatch.setattr(
            "app.services.web_clip_service._hostname_resolves_internal", lambda host: False
        )
        html = (
            "<html><body><article><h1>Recipe</h1>"
            "<p>Preheat the oven to 180C. Bake for 30 minutes.</p></article></body></html>"
        )
        with respx.mock:
            respx.get("https://example.com/cooking").mock(
                return_value=httpx.Response(
                    200, text=html, headers={"content-type": "text/html; charset=utf-8"}
                )
            )
            r = await client.post(
                "/api/v1/notes/web-clip", json={"url": "https://example.com/cooking"}
            )
        assert r.status_code == 200, r.text
        md = r.json()["markdown"]
        assert "Recipe" in md
        assert "180C" in md

    async def test_blocks_loopback(self, client: AsyncClient):
        # No network — the SSRF guard rejects before fetching.
        r = await client.post(
            "/api/v1/notes/web-clip", json={"url": "http://127.0.0.1:18765/secret"}
        )
        assert r.status_code == 400

    async def test_blocks_link_local_metadata(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/notes/web-clip",
            json={"url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert r.status_code == 400

    async def test_rejects_non_html(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(
            "app.services.web_clip_service._hostname_resolves_internal", lambda host: False
        )
        with respx.mock:
            respx.get("https://example.com/file.pdf").mock(
                return_value=httpx.Response(
                    200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
                )
            )
            r = await client.post(
                "/api/v1/notes/web-clip", json={"url": "https://example.com/file.pdf"}
            )
        assert r.status_code == 400

    async def test_rejects_invalid_scheme(self, client: AsyncClient):
        # Pydantic HttpUrl only allows http/https → 422 validation error.
        r = await client.post(
            "/api/v1/notes/web-clip", json={"url": "file:///etc/passwd"}
        )
        assert r.status_code == 422

    async def test_blocks_redirect_to_internal(self, client: AsyncClient, monkeypatch):
        # Regression for the SSRF-via-redirect bypass: an external host that
        # 302-redirects to a link-local/internal address must be blocked, even
        # though the *initial* URL is public.
        monkeypatch.setattr(
            "app.services.web_clip_service._hostname_resolves_internal", lambda host: False
        )
        with respx.mock:
            respx.get("https://attacker.example/clip").mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
                )
            )
            respx.get("http://169.254.169.254/latest/meta-data/").mock(
                return_value=httpx.Response(
                    200, text="<p>secret</p>", headers={"content-type": "text/html"}
                )
            )
            r = await client.post(
                "/api/v1/notes/web-clip", json={"url": "https://attacker.example/clip"}
            )
        assert r.status_code == 400

    async def test_blocks_hostname_resolving_internal(self, client: AsyncClient, monkeypatch):
        # DNS-rebinding guard: a hostname that resolves to an internal IP is blocked.
        monkeypatch.setattr(
            "app.services.web_clip_service._hostname_resolves_internal", lambda host: True
        )
        r = await client.post(
            "/api/v1/notes/web-clip", json={"url": "https://internal.example/"}
        )
        assert r.status_code == 400
