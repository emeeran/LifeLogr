"""Guards on the destructive endpoints (POST /api/v1/entries/reset).

Three layers are exercised, in middleware order:

1. the shared ``API_TOKEN`` gate (already covers every ``/api/*`` path when the
   token is configured — verified here rather than assumed);
2. the destructive-endpoint origin rule: an Origin the deployment does not
   itself use — including *another loopback port*, which the generic CSRF guard
   trusts — is rejected;
3. an always-on throttle, since the generic rate limiter is production-only and
   therefore off in the desktop default.

Non-browser clients (no Origin header) are unaffected by layers 2 and 3's
origin rule — that is what keeps curl and the sidecar's own scripts working.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _clear_rate_store():
    """The destructive throttle is in-memory and process-wide: isolate it."""
    import app.main as main_mod

    main_mod._rate_store.clear()
    yield
    main_mod._rate_store.clear()


async def _reset(client: AsyncClient, **headers: str):
    return await client.post(
        "/api/v1/entries/reset", json={"confirm": "RESET"}, headers=headers or None
    )


class TestOriginRule:
    async def test_no_origin_is_allowed(self, client: AsyncClient):
        """curl / sidecar scripts send no Origin and are unaffected."""
        assert (await _reset(client)).status_code == 200

    async def test_another_loopback_port_is_rejected(self, client: AsyncClient):
        """The generic CSRF guard trusts any loopback origin; this one must not.

        A hostile page served from another local port is exactly the cross-site
        case the generic guard cannot see, because its rule is host-based.
        """
        r = await _reset(client, Origin="http://localhost:9999")
        assert r.status_code == 403
        assert "Cross-origin" in r.json()["detail"]

    async def test_another_loopback_referer_is_rejected_too(self, client: AsyncClient):
        r = await _reset(client, Referer="http://127.0.0.1:9999/settings")
        assert r.status_code == 403

    async def test_a_configured_cors_origin_is_allowed(self, client: AsyncClient):
        """The Vite dev server origin is in CORS_ORIGINS — the SPA must keep working."""
        from app.core.config import settings

        origin = settings.CORS_ORIGINS.split(",")[0]
        assert origin and origin != ""
        assert (await _reset(client, Origin=origin)).status_code == 200

    async def test_a_tauri_origin_is_allowed(self, client: AsyncClient):
        assert (await _reset(client, Origin="tauri://localhost")).status_code == 200

    async def test_same_origin_with_the_host_header_is_allowed(self, client: AsyncClient):
        """The test harness drives the app as http://test — same-origin passes."""
        r = await _reset(client, Origin="http://test")
        assert r.status_code == 200


class TestAlwaysOnThrottle:
    async def test_more_than_five_wipes_per_minute_are_throttled(self, client: AsyncClient):
        for _ in range(5):
            assert (await _reset(client)).status_code == 200
        r = await _reset(client)
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert int(r.headers["Retry-After"]) >= 1
        assert "Too many" in r.json()["detail"]

    async def test_the_throttle_runs_even_outside_production(self, client: AsyncClient):
        """The generic limiter is production-only; this one must not be.

        APP_ENV in the test harness is "test", so a 429 here proves the guard is
        independent of the production gate.
        """
        from app.core.config import settings

        assert not settings.is_production
        for _ in range(6):
            await _reset(client)
        assert (await _reset(client)).status_code == 429

    async def test_the_throttle_ages_out_of_its_window(self, client: AsyncClient):
        import time

        import app.main as main_mod

        for _ in range(5):
            assert (await _reset(client)).status_code == 200
        assert (await _reset(client)).status_code == 429

        # Age every hit out of the window: the same client may wipe again.
        aged = time.time() - main_mod._DESTRUCTIVE_RATE_WINDOW - 1
        for key in list(main_mod._rate_store):
            if key.startswith("destructive:"):
                main_mod._rate_store[key] = [aged]
        assert (await _reset(client)).status_code == 200


class TestOriginDecisionTable:
    """Unit coverage for the origin predicate the destructive guard applies."""

    @pytest.mark.parametrize(
        ("origin", "host", "allowed"),
        [
            ("http://localhost:5173", "127.0.0.1:18765", True),  # configured CORS origin
            ("tauri://localhost", "127.0.0.1:18765", True),  # desktop webview
            ("http://test", "test", True),  # same-origin (harness host)
            ("http://localhost:9999", "127.0.0.1:18765", False),  # hostile local port
            ("http://evil.example", "127.0.0.1:18765", False),  # remote page
            ("", "127.0.0.1:18765", False),  # empty origin is not "trusted"
        ],
    )
    def test_origin_allowance(self, origin: str, host: str, allowed: bool):
        from app.main import _origin_allowed_for_destructive

        assert _origin_allowed_for_destructive(origin, host) is allowed


class TestTokenGate:
    async def test_reset_requires_the_token_when_one_is_configured(
        self, client: AsyncClient, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "API_TOKEN", "s3cret")
        assert (await _reset(client)).status_code == 401

        r = await client.post(
            "/api/v1/entries/reset",
            json={"confirm": "RESET"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert r.status_code == 200

    async def test_wrong_token_is_rejected(self, client: AsyncClient, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "API_TOKEN", "s3cret")
        r = await client.post(
            "/api/v1/entries/reset",
            json={"confirm": "RESET"},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401


class TestConfirmation:
    async def test_wrong_confirm_value_is_still_rejected(self, client: AsyncClient):
        r = await client.post("/api/v1/entries/reset", json={"confirm": "reset"})
        assert r.status_code == 400
        assert "Confirmation required" in r.json()["detail"]

    async def test_confirm_comparison_is_constant_time(self):
        """Hygiene: the confirmation is matched with compare_digest, not ==."""
        import inspect

        from app.routers import entries as entries_mod

        source = inspect.getsource(entries_mod.reset_database)
        assert "compare_digest" in source
