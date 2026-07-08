"""OneDrive (Microsoft Graph) OAuth 2.0 route handlers."""

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

router = APIRouter(prefix="/api/v1/backup/onedrive", tags=["backup-onedrive"])

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/onedrive/callback"
SCOPES = "Files.ReadWrite.AppFolder offline_access"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

_state = OAuthStateStore()


def _result_page(ok: bool, detail: str = "") -> HTMLResponse:
    title = "OneDrive Connected" if ok else "Connection Failed"
    emoji = "✅" if ok else "❌"
    body = (
        "LifeLogr connected to your OneDrive account. You can close this tab."
        if ok
        else detail
    )
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><body style='font-family:sans-serif;background:#0f172a;color:#f8fafc;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center'>"
            f"<div><div style='font-size:3rem'>{emoji}</div><h2>{title}</h2>"
            f"<p style='color:#94a3b8'>{body}</p></div></body></html>"
        ),
        status_code=200 if ok else 400,
    )


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the OneDrive OAuth consent URL."""
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "onedrive"))
    config = result.scalar_one_or_none()
    client_id = settings.ONEDRIVE_CLIENT_ID
    if config:
        try:
            client_id = json.loads(decrypt(config.credentials_encrypted)).get("client_id", client_id)
        except Exception:
            logger.warning("Failed to decrypt stored OneDrive credentials", exc_info=True)
    if not client_id:
        raise HTTPException(status_code=400, detail="OneDrive OAuth client_id is not configured")

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "state": _state.issue(),
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(...),
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the OneDrive auth code for tokens and save the config."""
    if not _state.consume(state):
        return _result_page(False, "Invalid or expired OAuth state. Please retry.")

    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "onedrive"))
    config = result.scalar_one_or_none()

    client_id = settings.ONEDRIVE_CLIENT_ID
    client_secret = settings.ONEDRIVE_CLIENT_SECRET
    stored: dict[str, str] = {}
    if config:
        try:
            stored = json.loads(decrypt(config.credentials_encrypted))
            client_id = stored.get("client_id", client_id)
            client_secret = stored.get("client_secret", client_secret)
        except Exception:
            logger.warning("Failed to decrypt OneDrive credentials for token exchange", exc_info=True)
    if not client_id or not client_secret:
        return _result_page(False, "OneDrive client_id/client_secret are not configured")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "scope": SCOPES,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            token_data = resp.json()
        except Exception as e:
            return _result_page(False, f"Failed to exchange code: {e}")

    refresh_token = token_data.get("refresh_token") or stored.get("refresh_token")
    if not refresh_token:
        return _result_page(False, "No refresh token returned. Please retry.")
    new_creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": token_data["access_token"],
        "refresh_token": refresh_token,
        "token_expiry": str(time.time() + token_data["expires_in"]),
    }
    encrypted = encrypt(json.dumps(new_creds))
    if config:
        config.credentials_encrypted = encrypted
    else:
        db.add(BackupConfig(provider="onedrive", credentials_encrypted=encrypted))
    await db.commit()
    return _result_page(True)
