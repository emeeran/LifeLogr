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
        r = await client.get("/api/v1/export/markdown")
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
