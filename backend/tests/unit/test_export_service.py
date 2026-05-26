"""Integration tests for export — HTML export."""

from httpx import AsyncClient


class TestExportHTML:
    async def test_export_html(self, client: AsyncClient):
        await client.post(
            "/api/v1/entries", json={"entry_date": "2026-05-01", "body": "**Bold** text"}
        )
        r = await client.get("/api/v1/export/html")
        assert r.status_code == 200
        assert "Bold" in r.text
