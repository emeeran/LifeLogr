"""Google OAuth + authenticated REST helper for Calendar, Tasks & Contacts sync.

Mirrors the Drive provider's token model (``cloud_sync_service.GoogleDriveProvider``)
but generalized for any Google REST API, so ``CalendarSyncService``,
``TasksSyncService`` and ``ContactsSyncService`` share one client. Gmail is
**not** handled here — it stays on its own IMAP connection.

Credentials are the same JSON shape as BackupConfig:
``{client_id, client_secret, access_token, refresh_token, token_expiry}``,
AES-encrypted at rest via ``app.core.security``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/google/callback"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Read/write scopes for two-way sync.
AUTH_SCOPES = (
    "https://www.googleapis.com/auth/calendar "
    "https://www.googleapis.com/auth/tasks "
    "https://www.googleapis.com/auth/contacts"
)

# Credentials JSON shape stored (encrypted) on GoogleSyncAccount.
Credentials = dict[str, str]
TokenRefreshCallback = Callable[[str, str], Awaitable[None]]


def build_auth_url(client_id: str, state: str) -> str:
    """Build the Google consent URL for Calendar+Tasks+Contacts scopes."""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": AUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


async def exchange_code(code: str, client_id: str, client_secret: str) -> Credentials:
    """Exchange an authorization code for a credentials bundle.

    ``client_id``/``client_secret`` are resolved by the caller (DB-stored app
    config first, then ``settings`` env — see ``routers/google_sync.py``).
    Raises ``RuntimeError`` if either is missing or Google didn't return a
    refresh token, or ``httpx.HTTPStatusError`` on a failed exchange.
    """
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID/SECRET are not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh_token — revoke the app at "
            "myaccount.google.com/permissions and re-link."
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": data["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + data["expires_in"]),
    }


class GoogleAPIClient:
    """Authenticated Google REST client with automatic token refresh.

    Construct with a credentials dict (the decrypted ``GoogleSyncAccount``
    payload) and an optional ``on_token_refresh`` callback that persists
    refreshed tokens back to the DB. Every request carries
    ``Authorization: Bearer <access_token>``.
    """

    def __init__(
        self,
        credentials: Credentials,
        on_token_refresh: TokenRefreshCallback | None = None,
    ) -> None:
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self._refresh_token = credentials.get("refresh_token")
        self._access_token = credentials.get("access_token")
        self._token_expiry = credentials.get("token_expiry")
        self._on_token_refresh = on_token_refresh
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GoogleAPIClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _ensure_valid_token(self) -> str:
        now = time.time()
        if self._access_token and self._token_expiry and float(self._token_expiry) > now + 60:
            return self._access_token
        if not self._refresh_token:
            raise RuntimeError("Refresh token missing from Google credentials")
        if not self._client_id or not self._client_secret:
            raise RuntimeError("Google OAuth client credentials are not configured")

        client = self._get_client()
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = str(now + data["expires_in"])
        if self._on_token_refresh:
            await self._on_token_refresh(self._access_token, self._token_expiry)
        return self._access_token

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        if_match: str | None = None,
    ) -> httpx.Response:
        """Perform an authenticated Google API request; raises on non-2xx.

        ``if_match`` adds an ``If-Match: <etag>`` header for Calendar optimistic
        concurrency (the API returns 412 when the remote changed since ``etag``).
        """
        token = await self._ensure_valid_token()
        h = {"Authorization": f"Bearer {token}"}
        if headers:
            h.update(headers)
        if if_match:
            h["If-Match"] = if_match
        client = self._get_client()
        resp = await client.request(
            method, url, params=params, json=json_body, headers=h, timeout=timeout
        )
        resp.raise_for_status()
        return resp
