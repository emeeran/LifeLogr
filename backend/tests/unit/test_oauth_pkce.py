"""Tests for PKCE (S256) on the four cloud-backup OAuth flows.

An authorization code transits the browser, so ``state`` alone is not enough:
each flow now carries a code_challenge in the consent URL and the matching
code_verifier (held only in the backend) at the token exchange.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.core.config import settings

# provider → (authorize path, mocked token URL, success-page marker)
_PROVIDERS: dict[str, tuple[str, str, str]] = {
    "google-drive": (
        "/api/v1/backup/google-drive",
        "https://oauth2.googleapis.com/token",
        "Google Drive Connected",
    ),
    "onedrive": (
        "/api/v1/backup/onedrive",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "OneDrive Connected",
    ),
    "dropbox": (
        "/api/v1/backup/dropbox",
        "https://api.dropboxapi.com/oauth2/token",
        "Dropbox Connected",
    ),
    "box": (
        "/api/v1/backup/box",
        "https://api.box.com/oauth2/token",
        "Box Connected",
    ),
}


@pytest.fixture(autouse=True)
def _oauth_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every provider a client id/secret without touching the DB."""
    for provider in _PROVIDERS:
        prefix = provider.split("-")[0].upper()  # GOOGLE / ONEDRIVE / DROPBOX / BOX
        monkeypatch.setattr(settings, f"{prefix}_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(settings, f"{prefix}_CLIENT_SECRET", "test-client-secret")


def _query(auth_url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(auth_url).query)


class TestPkceStorePrimitives:
    def test_verifier_length_and_alphabet(self) -> None:
        from app.core.oauth_state import generate_code_verifier

        for _ in range(5):
            verifier = generate_code_verifier()
            assert 43 <= len(verifier) <= 128
            assert all(c.isalnum() or c in "-._~" for c in verifier)

    def test_verifiers_are_unique(self) -> None:
        from app.core.oauth_state import generate_code_verifier

        assert len({generate_code_verifier() for _ in range(20)}) == 20

    def test_issue_with_pkce_binds_verifier_to_state(self) -> None:
        from app.core.oauth_state import OAuthStateStore, code_challenge_s256

        store = OAuthStateStore()
        state, verifier, challenge = store.issue_with_pkce()
        assert challenge == code_challenge_s256(verifier)
        # Single use: the verifier is handed over exactly once.
        assert store.take(state) == verifier
        assert store.take(state) is None

    def test_take_rejects_unknown_and_missing_state(self) -> None:
        from app.core.oauth_state import OAuthStateStore

        store = OAuthStateStore()
        store.issue_with_pkce()
        assert store.take("forged") is None
        assert store.take(None) is None

    def test_states_without_pkce_still_consume(self) -> None:
        from app.core.oauth_state import OAuthStateStore

        store = OAuthStateStore()
        state = store.issue()
        assert store.consume(state) is True


class TestPkcePerProvider:
    @respx.mock
    @pytest.mark.parametrize("provider", sorted(_PROVIDERS))
    async def test_challenge_sent_and_verifier_exchanged(
        self, client: AsyncClient, provider: str
    ) -> None:
        prefix, token_url, marker = _PROVIDERS[provider]

        captured: dict[str, Any] = {}

        def _capture(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(
                200,
                json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
            )

        respx.post(token_url).mock(side_effect=_capture)

        auth = await client.get(f"{prefix}/auth-url")
        assert auth.status_code == 200, auth.text
        q = _query(auth.json()["auth_url"])
        assert q["code_challenge_method"] == ["S256"]
        challenge = q["code_challenge"][0]
        assert 43 <= len(challenge) <= 128

        r = await client.get(
            f"{prefix}/callback", params={"code": "auth-code", "state": q["state"][0]}
        )
        assert r.status_code == 200, r.text
        assert marker in r.text

        assert "code_verifier=" in captured["body"], captured["body"]
        # challenge must be the S256 digest of the verifier that was sent
        from app.core.oauth_state import code_challenge_s256

        verifier = captured["body"].split("code_verifier=")[1].split("&")[0]
        assert code_challenge_s256(verifier) == challenge

    @pytest.mark.parametrize("provider", sorted(_PROVIDERS))
    async def test_callback_without_valid_state_is_refused(
        self, client: AsyncClient, provider: str
    ) -> None:
        prefix, _, _ = _PROVIDERS[provider]
        r = await client.get(f"{prefix}/callback", params={"code": "auth-code", "state": "forged"})
        assert r.status_code == 400
        assert "state" in r.text.lower()


class TestConsentDenied:
    """A user-declined consent must render the styled error page, not a 422."""

    @pytest.mark.parametrize("provider", sorted(_PROVIDERS))
    async def test_provider_error_redirect_is_handled(
        self, client: AsyncClient, provider: str
    ) -> None:
        prefix, _, _ = _PROVIDERS[provider]
        r = await client.get(
            f"{prefix}/callback",
            params={"error": "access_denied", "error_description": "user denied"},
        )
        assert r.status_code == 400
        assert "access_denied" in r.text
        assert "user denied" in r.text
