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
from typing import Any

import httpx
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt
from app.models.backup import BackupConfig

logger = logging.getLogger(__name__)

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
