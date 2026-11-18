"""Shared helpers for the cloud-backup OAuth loopback callback routers.

The four OAuth providers (Google Drive / Dropbox / OneDrive / Box) run the same
loopback dance: exchange the auth code for tokens, encrypt + upsert the
credentials, and render a success/error page. The provider-specific bits (token
URL, request body, credential shape, scopes) stay in each router; the identical
exchange / upsert / render plumbing lives here so it isn't copy-pasted four times
(with four copies of the same HTML).
"""

from __future__ import annotations

import html
import json
import logging
import time
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import is_loopback_host, settings
from app.core.oauth_state import OAuthStateStore
from app.core.security import decrypt, encrypt
from app.models.backup import BackupConfig

logger = logging.getLogger(__name__)


def loopback_redirect_uri(request: Request, path: str) -> str:
    """Build the OAuth loopback redirect URI for *path* from the request host.

    The backend's port is chosen at launch (18765 in the packaged app, any free
    port under ``dev.sh``), so it cannot be a module constant — Google must be
    sent back to the same host:port the caller used to reach this backend, and
    the callback must derive the identical URI for the token exchange (Google
    rejects a mismatched ``redirect_uri``). Only loopback hosts are honoured:
    a spoofed Host header falls back to the configured bind address so the
    authorization code can never be redirected off-machine.
    """
    host_header = request.headers.get("host", "")
    hostname, _, port = host_header.rpartition(":")
    if not hostname or not port.isdigit() or not is_loopback_host(hostname):
        hostname, port = "127.0.0.1", str(settings.BIND_PORT)
    if is_loopback_host(hostname) and ":" in hostname:
        hostname = f"[{hostname.strip('[]')}]"  # IPv6 literals need brackets in URLs
    return f"http://{hostname}:{port}{path}"

_SUCCESS_HTML = """<!DOCTYPE html><html><head><title>__TITLE__</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;background:#1e293b;padding:3rem;border-radius:1.5rem;max-width:450px;border:1px solid #334155}
h1{color:#10b981;font-size:1.85rem}.logo{font-size:4.5rem}p{color:#94a3b8;line-height:1.6}</style></head>
<body><div class="card"><div class="logo">__EMOJI__</div><h1>__TITLE__</h1>
<p>__MESSAGE__</p><p>You can close this tab and return to the app.</p></div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html><html><head><title>Connection Failed</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;background:#1e293b;padding:3rem;border-radius:1.5rem;max-width:450px;border:1px solid #ef4444}
h1{color:#ef4444;font-size:1.85rem}.logo{font-size:4.5rem}.err{background:#0f172a;padding:1rem;border-radius:.5rem;font-family:monospace;font-size:.85rem;color:#f87171;word-break:break-all;text-align:left}</style></head>
<body><div class="card"><div class="logo">❌</div><h1>Authentication Failed</h1>
<div class="err">__DETAIL__</div></div></body></html>"""


def success_page(title: str, emoji: str, message: str) -> HTMLResponse:
    """Render the OAuth success page for a provider.

    Uses placeholder replacement (not ``str.format``) so the literal CSS braces
    in the template aren't mistaken for format fields.
    """
    page = (
        _SUCCESS_HTML.replace("__TITLE__", html.escape(title))
        .replace("__EMOJI__", emoji)
        .replace("__MESSAGE__", html.escape(message))
    )
    return HTMLResponse(content=page, status_code=200)


def error_page(detail: str) -> HTMLResponse:
    """Render the OAuth failure page with a safe (HTML-escaped) detail string."""
    return HTMLResponse(
        content=_ERROR_HTML.replace("__DETAIL__", html.escape(detail)), status_code=400
    )


def load_stored_credentials(config: BackupConfig | None, provider_label: str) -> dict[str, str]:
    """Decrypt a provider's stored credentials; ``{}`` when unreadable.

    A corrupt/undecryptable blob must not block the flow — the caller falls
    back to env-configured client ids — so failures are logged and swallowed
    by design.
    """
    if config is None:
        return {}
    try:
        stored = json.loads(decrypt(config.credentials_encrypted))
        return stored if isinstance(stored, dict) else {}
    except Exception:
        logger.warning("Failed to decrypt stored %s credentials", provider_label, exc_info=True)
        return {}


async def exchange_authorization_code(
    token_url: str, data: dict[str, str], timeout: float = 10.0
) -> dict[str, Any]:
    """POST an authorization-code exchange; return the parsed token JSON.

    Raises ``httpx.HTTPError`` on transport/HTTP failure — the caller catches
    and renders a provider-specific error page (no internals leaked).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data, timeout=timeout)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


async def upsert_backup_config(
    db: AsyncSession,
    provider: str,
    creds: dict[str, Any],
    existing: BackupConfig | None = None,
) -> None:
    """Encrypt *creds* and insert/update the provider's BackupConfig row."""
    encrypted = encrypt(json.dumps(creds))
    if existing is not None:
        existing.credentials_encrypted = encrypted
    else:
        db.add(BackupConfig(provider=provider, credentials_encrypted=encrypted))
    await db.commit()


async def oauth_callback_flow(
    request: Request,
    db: AsyncSession,
    state_store: OAuthStateStore,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
    provider: str,
    label: str,
    token_url: str,
    redirect_path: str,
    default_client_id: str | None,
    default_client_secret: str | None,
    success_title: str,
    success_message: str,
    extra_exchange_data: dict[str, str] | None = None,
    exchange_timeout: float = 10.0,
    default_expires_in: int | None = None,
    allow_stored_refresh_token: bool = True,
    missing_refresh_message: str = "No refresh token returned. Please retry.",
) -> HTMLResponse:
    """The shared OAuth loopback callback: validate, exchange, upsert, render.

    All four provider routers (Google Drive / Dropbox / OneDrive / Box) run the
    identical flow — this is its single implementation. The caller supplies the
    provider-specific bits: token URL, default credentials, any extra exchange
    fields (e.g. OneDrive's ``scope``), and page text. The ``code``/``state``/
    ``error`` query params come in as FastAPI-bound arguments.

    Credentials resolve to stored-over-env: a previous connection's
    ``client_id``/``client_secret`` win over the env-configured defaults (an
    empty stored value falls through to the default).
    """
    if error:
        msg = f"{label} denied the request: {error}"
        if error_description:
            msg += f" — {error_description}"
        return error_page(msg)
    if not code:
        return error_page(f"{label} returned no authorization code.")

    # Single-use consume; the verifier is what makes the (browser-visible)
    # code exchangeable, so a stolen or replayed code is dead on arrival.
    code_verifier = state_store.take(state)
    if not code_verifier:
        return error_page("Invalid or expired OAuth state. Please retry connection.")

    config = (
        await db.execute(select(BackupConfig).where(BackupConfig.provider == provider))
    ).scalar_one_or_none()
    stored = load_stored_credentials(config, label)

    client_id = stored.get("client_id") or default_client_id
    client_secret = stored.get("client_secret") or default_client_secret
    if not client_id or not client_secret:
        return error_page(f"{label} OAuth client_id/client_secret are not configured")

    exchange_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": loopback_redirect_uri(request, redirect_path),
        "code_verifier": code_verifier,
        **(extra_exchange_data or {}),
    }
    try:
        tokens = await exchange_authorization_code(
            token_url, exchange_data, timeout=exchange_timeout
        )
    except Exception:
        logger.warning("%s token exchange failed", label, exc_info=True)
        return error_page(f"Failed to connect to {label}. Please retry.")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token and allow_stored_refresh_token:
        refresh_token = stored.get("refresh_token")
    if not refresh_token:
        return error_page(missing_refresh_message)

    expires_in: int | None = tokens.get("expires_in")
    if expires_in is None and default_expires_in is not None:
        expires_in = default_expires_in
    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": tokens["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + (expires_in or 0)),
    }
    try:
        await upsert_backup_config(db, provider, new_creds, existing=config)
    except Exception:
        logger.warning("Failed to persist %s credentials", label, exc_info=True)
        return error_page(f"Failed to save the {label} connection. Please retry.")

    return success_page(success_title, "✅", success_message)
