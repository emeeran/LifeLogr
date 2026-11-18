"""OneDrive provider OAuth token-refresh contract.

This is the shared flow that T3.1's ``BaseOAuthProvider`` will extract across the
OAuth providers (Google / OneDrive / Dropbox / Box): when the cached access token
is expired, ``_ensure_valid_token`` refreshes it via the provider's token
endpoint, rotates the refresh token when the provider returns a new one, and
fires ``on_token_refresh`` so the caller can persist the refreshed credentials.
Locking it here gives the T3.1 refactor a regression net.
"""

from __future__ import annotations

import time

import httpx
import respx

from app.services.cloud_sync_service import (
    BoxProvider,
    DropboxProvider,
    OneDriveProvider,
)


def _creds(expired: bool = True) -> dict[str, str]:
    return {
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rt-old",
        "access_token": "token-old",
        "token_expiry": str(time.time() - 60 if expired else time.time() + 3600),
    }


@respx.mock
async def test_refreshes_expired_token_and_invokes_callback() -> None:
    captured: dict[str, str] = {}

    async def on_refresh(access: str, expiry: str) -> None:
        captured["access_token"] = access
        captured["token_expiry"] = expiry

    provider = OneDriveProvider(_creds(expired=True), on_token_refresh=on_refresh)
    respx.post(OneDriveProvider.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "token-new",
                "expires_in": 3600,
                "refresh_token": "rt-rotated",
            },
        )
    )
    respx.get(f"{OneDriveProvider.GRAPH}/children").mock(
        return_value=httpx.Response(
            200, json={"value": [{"name": "lifelogr-backup-2026.tar.gz"}]}
        )
    )

    names = await provider.list_files("lifelogr-backup-")
    await provider.close()

    assert names == ["lifelogr-backup-2026.tar.gz"]
    # The refresh fired and the callback observed the new token.
    assert captured["access_token"] == "token-new"
    # The provider now holds the refreshed token + the rotated refresh token.
    assert provider._access_token == "token-new"
    assert provider._refresh_token == "rt-rotated"


@respx.mock
async def test_skips_refresh_when_token_still_valid() -> None:
    provider = OneDriveProvider(_creds(expired=False))
    respx.get(f"{OneDriveProvider.GRAPH}/children").mock(
        return_value=httpx.Response(200, json={"value": [{"name": "a.tar.gz"}]})
    )

    names = await provider.list_files("a")
    await provider.close()

    assert names == ["a.tar.gz"]
    # No token-refresh POST was made — only the list GET.
    token_calls = [
        call for call in respx.calls if str(call.request.url) == OneDriveProvider.TOKEN_URL
    ]
    assert token_calls == []


# ── Dropbox + Box: same contract, exercised directly via _ensure_valid_token ─


@respx.mock
async def test_dropbox_refreshes_and_invokes_2arg_callback() -> None:
    captured: dict[str, str] = {}

    async def on_refresh(access: str, expiry: str) -> None:
        captured["access_token"] = access
        captured["token_expiry"] = expiry

    provider = DropboxProvider(_creds(expired=True), on_token_refresh=on_refresh)
    respx.post(DropboxProvider.TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "db-new", "expires_in": 3600}
        )
    )

    token = await provider._ensure_valid_token()
    await provider.close()

    assert token == "db-new"
    assert provider._access_token == "db-new"
    assert captured["access_token"] == "db-new"  # 2-arg callback fired


@respx.mock
async def test_box_refreshes_rotates_and_invokes_3arg_callback() -> None:
    captured: dict[str, str] = {}

    async def on_refresh(access: str, refresh: str, expiry: str) -> None:
        captured["access_token"] = access
        captured["refresh_token"] = refresh
        captured["token_expiry"] = expiry

    provider = BoxProvider(_creds(expired=True), on_token_refresh=on_refresh)
    respx.post(BoxProvider.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "box-new",
                "expires_in": 3600,
                "refresh_token": "rt-rotated",  # Box rotates every refresh
            },
        )
    )

    token = await provider._ensure_valid_token()
    await provider.close()

    assert token == "box-new"
    assert provider._access_token == "box-new"
    assert provider._refresh_token == "rt-rotated"  # rotated refresh token kept
    # 3-arg callback fired with the rotated refresh token.
    assert captured["access_token"] == "box-new"
    assert captured["refresh_token"] == "rt-rotated"
