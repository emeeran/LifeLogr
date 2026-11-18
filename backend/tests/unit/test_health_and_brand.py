"""Tests for top-level endpoints: /health and /api/v1/brand/logo."""

from httpx import AsyncClient


class TestHealth:
    async def test_returns_structured_checks(self, client: AsyncClient):
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        # Each subsystem reported independently (graceful degradation).
        assert "checks" in data
        assert data["checks"]["database"] == "ok"


class TestBrandLogo:
    async def test_returns_png_when_assets_present(self, client: AsyncClient):
        """In dev/test the source assets/ dir is on disk → 200 image/png."""
        r = await client.get("/api/v1/brand/logo")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        # PNG magic bytes
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_graceful_404_when_assets_absent(self, client: AsyncClient, monkeypatch):
        """When neither PNG nor SVG exist (e.g. frozen build), return 404, not 500."""
        from pathlib import Path

        import tempfile

        # Point the assets dir at an empty temp dir so both logos are absent.
        empty = Path(tempfile.mkdtemp())
        monkeypatch.setattr("app.main._ASSETS_DIR", empty)

        r = await client.get("/api/v1/brand/logo")
        assert r.status_code == 404
        assert "not available" in r.json()["detail"].lower()
