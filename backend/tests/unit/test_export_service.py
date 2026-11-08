"""Integration tests for export — HTML and Markdown export."""

from httpx import AsyncClient


class TestExportHTML:
    async def test_export_html(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "**Bold** text"}
        )
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        assert "Bold" in r.text


class TestExportMarkdown:
    async def test_export_markdown(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries",
            json={
                "entry_date": "2026-05-02",
                "body": "Markdown test entry",
                "title": "Obsidian Export",
            },
        )
        r = await client.get("/api/v1/export/obsidian-vault")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"

        # Verify it is a valid zip file and check contents
        import io
        import zipfile

        zip_file = zipfile.ZipFile(io.BytesIO(r.content))
        file_list = zip_file.namelist()

        # Check that the entry markdown file is in the zip under journal/2026/05/2026-05-02.md
        md_file_path = "journal/2026/05/2026-05-02.md"
        assert md_file_path in file_list

        # Read the file and verify content & manually serialized yaml
        content = zip_file.read(md_file_path).decode("utf-8")
        assert 'date: "2026-05-02"' in content
        assert "title: Obsidian Export" in content
        assert "Markdown test entry" in content


NOTE_TEXT = "Attachments of this encrypted entry are omitted from exports."


async def _encrypted_entry(client: AsyncClient) -> dict:
    r = await client.post(
        "/api/v1/entries", json={"entry_date": "2026-06-01", "body": "Secret diary"}
    )
    assert r.status_code == 201
    entry = r.json()
    r = await client.post(
        f"/api/v1/entries/{entry['id']}/encryption/encrypt",
        json={"passphrase": "mypass"},
    )
    assert r.status_code == 200
    assert r.json()["is_encrypted"] is True
    return entry


def _pdf_text_content(raw: bytes) -> str:
    """Concatenate all FlateDecode content streams so text is greppable."""
    import re as _re
    import zlib

    chunks: list[str] = []
    for m in _re.finditer(rb"stream\r?\n(.*?)endstream", raw, _re.DOTALL):
        data = m.group(1)
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass  # already uncompressed
        chunks.append(data.decode("latin-1", "replace"))
    return "\n".join(chunks)


class TestExportEncryptedEntryNote:
    """SEC-MEDIA-7 follow-up: HTML/PDF exports surface the omission note inline,
    mirroring the Markdown frontmatter ``attachments_note``."""

    async def test_markdown_frontmatter_note(self, client: AsyncClient):
        import io
        import zipfile

        await _encrypted_entry(client)
        r = await client.get("/api/v1/export/obsidian-vault")
        assert r.status_code == 200
        zip_file = zipfile.ZipFile(io.BytesIO(r.content))
        content = zip_file.read("journal/2026/06/2026-06-01.md").decode("utf-8")
        assert NOTE_TEXT in content

    async def test_markdown_plain_entry_has_no_note(self, client: AsyncClient):
        import io
        import zipfile

        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-06-02", "body": "Open diary"}
        )
        r = await client.get("/api/v1/export/obsidian-vault")
        zip_file = zipfile.ZipFile(io.BytesIO(r.content))
        content = zip_file.read("journal/2026/06/2026-06-02.md").decode("utf-8")
        assert NOTE_TEXT not in content

    async def test_html_export_note(self, client: AsyncClient):
        await _encrypted_entry(client)
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-06-03", "body": "Open diary"}
        )
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        # Note present on the encrypted entry (marked-up class), absent on the plain one
        assert r.text.count(NOTE_TEXT) == 1
        assert 'class="encrypted-note"' in r.text

    async def test_html_zip_export_note(self, client: AsyncClient):
        import io
        import zipfile

        await _encrypted_entry(client)
        r = await client.get("/api/v1/entries/export/html-zip")
        assert r.status_code == 200
        zip_file = zipfile.ZipFile(io.BytesIO(r.content))
        page = zip_file.read("website/index.html").decode("utf-8")
        assert NOTE_TEXT in page
        assert 'class="encrypted-note"' in page

    async def test_pdf_export_note(self, client: AsyncClient):
        await _encrypted_entry(client)
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-06-04", "body": "Open diary"}
        )
        r = await client.get("/api/v1/export/pdf")
        assert r.status_code == 200
        text = _pdf_text_content(r.content)
        assert text.count(NOTE_TEXT) == 1
