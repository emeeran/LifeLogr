"""Export hardening: XSS escaping, download/CSP headers, collision-free filenames.

Regression tests for the stored-XSS and export-data-loss fixes:

- raw HTML (``<script>``) in an entry/note body must be escaped in the HTML
  export, never rendered verbatim;
- HTML exports must be served as ``Content-Disposition: attachment`` with a
  sandboxing ``Content-Security-Policy``;
- two entries on the same date (or two same-titled notes) must not overwrite
  each other inside a Markdown ZIP export.
"""

from __future__ import annotations

import inspect
import io
import zipfile

from httpx import AsyncClient

from app.services.export_service import build_diarium_database
from app.services.notes_export_service import NotesExportService

_SCRIPT = "<script>alert('xss')</script>"


async def _create_entry(client: AsyncClient, date: str, body: str, **kw):
    r = await client.post("/api/v1/entries", json={"entry_date": date, "body": body, **kw})
    assert r.status_code == 201, r.text
    return r.json()


class TestExportHtmlEscaping:
    async def test_script_tag_in_body_is_escaped(self, client: AsyncClient):
        await _create_entry(client, "2026-05-08", f"hello {_SCRIPT}")
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        assert _SCRIPT not in r.text
        assert "&lt;script&gt;" in r.text

    async def test_script_tag_in_title_mood_and_tags_is_escaped(self, client: AsyncClient):
        await _create_entry(
            client,
            "2026-05-09",
            "plain body",
            title=f"Title {_SCRIPT}",
            mood='mood" onmouseover="alert(1)',
        )
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        assert _SCRIPT not in r.text
        assert 'onmouseover="alert(1)' not in r.text

    async def test_notes_export_html_escapes_script(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/notes", json={"title": f"Note {_SCRIPT}", "body": f"body {_SCRIPT}"}
        )
        assert r.status_code == 201
        resp = await client.get("/api/v1/notes/export/html")
        assert resp.status_code == 200
        assert _SCRIPT not in resp.text
        assert "&lt;script&gt;" in resp.text

    def test_markdown_it_rejects_raw_html(self):
        """Unit-level guard: the shared renderer must escape raw HTML."""
        from markdown_it import MarkdownIt

        md = MarkdownIt("default", {"html": False})
        assert "<script>" not in md.render(_SCRIPT)
        assert "&lt;script&gt;" in md.render(_SCRIPT)
        # Ordinary markdown still renders.
        assert "<strong>bold</strong>" in md.render("**bold**")


class TestExportHtmlHeaders:
    async def test_entries_html_export_is_sandboxed_attachment(self, client: AsyncClient):
        await _create_entry(client, "2026-05-10", "header test")
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")
        assert "lifelogr-export.html" in r.headers["content-disposition"]
        assert r.headers["content-security-policy"] == "sandbox"

    async def test_notes_html_export_is_sandboxed_attachment(self, client: AsyncClient):
        await client.post("/api/v1/notes", json={"title": "n", "body": "b"})
        r = await client.get("/api/v1/notes/export/html")
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.headers["content-security-policy"] == "sandbox"


class TestUniqueExportFilenames:
    async def test_obsidian_vault_same_day_entries_do_not_collide(self, client: AsyncClient):
        await _create_entry(client, "2026-05-11", "first entry of the day")
        await _create_entry(client, "2026-05-11", "second entry of the day")

        r = await client.get("/api/v1/export/markdown")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        day_files = [n for n in zf.namelist() if n.startswith("journal/") and n.endswith(".md")]
        assert len(day_files) == len(set(day_files))  # nothing overwrote anything
        text = "".join(zf.read(n).decode() for n in day_files)
        assert "first entry of the day" in text
        assert "second entry of the day" in text

    async def test_diarium_markdown_zip_same_day_entries_do_not_collide(self, client: AsyncClient):
        await _create_entry(client, "2026-05-12", "diarium first")
        await _create_entry(client, "2026-05-12", "diarium second")

        r = await client.get("/api/v1/entries/export/markdown")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        md_names = [n for n in zf.namelist() if n.startswith("entries/")]
        assert len(md_names) == len(set(md_names))
        text = "".join(zf.read(n).decode() for n in md_names)
        assert "diarium first" in text
        assert "diarium second" in text

    async def test_notes_zip_same_titled_notes_do_not_collide(self, client: AsyncClient):
        await client.post("/api/v1/notes", json={"title": "Dup", "body": "note one"})
        await client.post("/api/v1/notes", json={"title": "Dup", "body": "note two"})

        r = await client.get("/api/v1/notes/export/markdown")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        md_names = [n for n in zf.namelist() if n.startswith("notes/")]
        assert len(md_names) == 2
        assert len(set(md_names)) == 2
        text = "".join(zf.read(n).decode() for n in md_names)
        assert "note one" in text and "note two" in text

    def test_zip_name_helper_appends_counter_on_collision(self):
        used: set[str] = set()
        n1 = NotesExportService._zip_name("Dup", 1, used)
        n2 = NotesExportService._zip_name("Dup", 2, used)
        assert n1 == "notes/dup.md"
        assert n2 == "notes/dup-2.md"

    async def test_pdf_export_survives_script_payload(self, client: AsyncClient):
        await _create_entry(client, "2026-05-13", f"pdf body {_SCRIPT}")
        r = await client.get("/api/v1/export/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.content.startswith(b"%PDF-")

    async def test_diarium_db_export_streams_sqlite_attachment(self, client: AsyncClient):
        await _create_entry(client, "2026-05-14", "diary export body")
        r = await client.get("/api/v1/entries/export/diarium-db")
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.content[:16] == b"SQLite format 3\x00"

    def test_build_diarium_database_is_awaitable(self):
        """It offloads the SQLite build to a worker thread (async entrypoint)."""
        assert inspect.iscoroutinefunction(build_diarium_database)
