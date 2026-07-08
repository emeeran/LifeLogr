"""Box OAuth 2.0 route handlers — mirrors google_drive.py.

Loopback flow: /auth-url builds the Box consent URL; Google/Box redirect to
REDIRECT_URI (port 18765), /callback exchanges the code for tokens and upserts
a BackupConfig(provider="box"). Box rotates its refresh token, so the stored
creds are rewritten whenever BackupService refreshes (see BoxProvider).
"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import OAuthStateStore
from app.core.security import decrypt, encrypt
from app.models.backup import BackupConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backup/box", tags=["backup-box"])

AUTHORIZE_URL = "https://account.box.com/api/oauth2/authorize"
TOKEN_URL = "https://api.box.com/oauth2/token"
REDIRECT_URI = "http://localhost:18765/api/v1/backup/box/callback"
_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the Box OAuth consent screen URL."""
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "box"))
    config = result.scalar_one_or_none()

    client_id = settings.BOX_CLIENT_ID
    if config:
        try:
            creds = json.loads(decrypt(config.credentials_encrypted))
            if creds.get("client_id"):
                client_id = creds["client_id"]
        except Exception:
            logger.warning("Failed to decrypt stored Box credentials", exc_info=True)

    if not client_id:
        raise HTTPException(status_code=400, detail="Box OAuth client_id is not configured")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": _state.issue(),
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str | None = Query(None, description="Authorization code from Box"),
    state: str | None = Query(None, description="OAuth state token"),
    error: str | None = Query(None, description="OAuth error from Box"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the Box OAuth loopback redirect: exchange code, save tokens."""
    if error:
        msg = f"Box denied the request: {error}"
        if error_description:
            msg += f" — {error_description}"
        return _render_error_page(msg)
    if not code:
        return _render_error_page("Box returned no authorization code.")
    if not _state.consume(state):
        return _render_error_page("Invalid or expired OAuth state. Please retry connection.")

    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "box"))
    config = result.scalar_one_or_none()

    client_id = settings.BOX_CLIENT_ID
    client_secret = settings.BOX_CLIENT_SECRET
    stored: dict[str, str] = {}
    if config:
        try:
            stored = json.loads(decrypt(config.credentials_encrypted))
            client_id = stored.get("client_id") or client_id
            client_secret = stored.get("client_secret") or client_secret
        except Exception:
            logger.warning("Failed to decrypt Box credentials for token exchange", exc_info=True)

    if not client_id or not client_secret:
        return _render_error_page("Box OAuth client_id/client_secret are not configured")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": REDIRECT_URI,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            tokens = resp.json()
        except Exception as e:
            return _render_error_page(f"Failed to exchange code: {e}")

    if not tokens.get("refresh_token"):
        return _render_error_page("No refresh token returned by Box. Please retry.")

    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_expiry": str(time.time() + tokens["expires_in"]),
    }
    encrypted = encrypt(json.dumps(new_creds))
    try:
        if config:
            config.credentials_encrypted = encrypted
        else:
            db.add(BackupConfig(provider="box", credentials_encrypted=encrypted))
        await db.commit()
    except Exception as e:
        return _render_error_page(f"Database error: {e}")

    return HTMLResponse(content=_SUCCESS_HTML, status_code=200)


def _render_error_page(detail: str) -> HTMLResponse:
    return HTMLResponse(
        content=_ERROR_HTML.replace("{{DETAIL}}", str(detail)), status_code=400
    )


_SUCCESS_HTML = """<!DOCTYPE html><html><head><title>Box Connected</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;background:#1e293b;padding:3rem;border-radius:1.5rem;max-width:450px;border:1px solid #334155}
h1{color:#10b981;font-size:1.85rem}.logo{font-size:4.5rem}p{color:#94a3b8;line-height:1.6}</style></head>
<body><div class="card"><div class="logo">📦</div><h1>Box Connected!</h1>
<p>LifeLogr is now connected to your Box account.</p>
<p>You can close this tab and return to the app.</p></div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html><html><head><title>Connection Failed</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;background:#1e293b;padding:3rem;border-radius:1.5rem;max-width:450px;border:1px solid #ef4444}
h1{color:#ef4444;font-size:1.85rem}.logo{font-size:4.5rem}.err{background:#0f172a;padding:1rem;border-radius:.5rem;font-family:monospace;font-size:.85rem;color:#f87171;word-break:break-all;text-align:left}</style></head>
<body><div class="card"><div class="logo">❌</div><h1>Authentication Failed</h1>
<div class="err">{{DETAIL}}</div></div></body></html>"""
