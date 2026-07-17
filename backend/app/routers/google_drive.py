"""Google Drive OAuth 2.0 route handlers."""

from __future__ import annotations

import html
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

router = APIRouter(prefix="/api/v1/backup/google-drive", tags=["backup-google-drive"])

REDIRECT_URI = "http://127.0.0.1:18765/api/v1/backup/google-drive/callback"
_state = OAuthStateStore()


def get_default_credentials() -> tuple[str, str]:
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate Google Drive OAuth consent screen URL."""
    # Look for existing custom client config in database
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_drive"))
    config = result.scalar_one_or_none()

    default_id, _ = get_default_credentials()
    client_id = default_id
    if config:
        try:
            creds = json.loads(decrypt(config.credentials_encrypted))
            if creds.get("client_id"):
                client_id = creds["client_id"]
        except Exception:
            logger.warning("Failed to decrypt stored Google credentials", exc_info=True)

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth client_id is not configured",
        )

    # drive.file: create/access the visible "LifeLogr Backups" folder.
    # drive.appdata: retained so older hidden backups can be migrated out.
    scopes = (
        "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.appdata"
    )
    auth_base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    state = _state.issue()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    return {"auth_url": f"{auth_base_url}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state token"),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle Google OAuth 2.0 loopback redirection, exchange code, and save tokens."""
    if not _state.consume(state):
        return _render_error_page("Invalid or expired OAuth state. Please retry connection.")

    # 1. Resolve client credentials
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_drive"))
    config = result.scalar_one_or_none()

    default_id, default_secret = get_default_credentials()
    client_id = default_id
    client_secret = default_secret

    stored_creds: dict[str, str] = {}
    if config:
        try:
            stored_creds = json.loads(decrypt(config.credentials_encrypted))
            client_id = stored_creds.get("client_id") or client_id
            client_secret = stored_creds.get("client_secret") or client_secret
        except Exception:
            logger.warning("Failed to decrypt Google credentials for token exchange", exc_info=True)

    if not client_id or not client_secret:
        return _render_error_page("Google OAuth client_id/client_secret are not configured")

    # 2. Exchange authorization code for tokens
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
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
            token_data = resp.json()
        except Exception as e:
            error_msg = f"Failed to exchange code: {str(e)}"
            return _render_error_page(error_msg)

    # 3. Encrypt and save configuration in DB
    try:
        new_creds = {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token")
            or (stored_creds.get("refresh_token") if config else None),
            "token_expiry": str(time.time() + token_data["expires_in"]),
        }

        if not new_creds["refresh_token"]:
            # If Google didn't return a refresh token (e.g. prompt=consent didn't fire properly or first-time sync),
            # return a helpful error page asking the user to retry.
            return _render_error_page("No refresh token returned. Please disconnect and try again.")

        encrypted_creds = encrypt(json.dumps(new_creds))

        if config:
            config.credentials_encrypted = encrypted_creds
        else:
            config = BackupConfig(
                provider="google_drive",
                credentials_encrypted=encrypted_creds,
            )
            db.add(config)

        await db.commit()
    except Exception as e:
        return _render_error_page(f"Database error: {str(e)}")

    # 4. Render success HTML response
    return HTMLResponse(content=_SUCCESS_HTML_PAGE, status_code=200)


def _render_error_page(detail: str) -> HTMLResponse:
    """Helper to render a beautiful error page."""
    page = _ERROR_HTML_TEMPLATE.replace("{{DETAIL}}", html.escape(detail))
    return HTMLResponse(content=page, status_code=400)


_SUCCESS_HTML_PAGE = """<!DOCTYPE html>
<html>
  <head>
    <title>Google Drive Connected</title>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #0f172a;
        color: #f8fafc;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100vh;
        margin: 0;
      }
      .card {
        text-align: center;
        background: #1e293b;
        padding: 3rem;
        border-radius: 1.5rem;
        box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
        max-width: 450px;
        border: 1px solid #334155;
      }
      h1 {
        color: #10b981;
        margin-top: 0;
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
      }
      p {
        color: #94a3b8;
        font-size: 1rem;
        line-height: 1.6;
        margin-bottom: 1.5rem;
      }
      .logo {
        font-size: 4.5rem;
        margin-bottom: 1.5rem;
        animation: scaleIn 0.5s ease-out;
      }
      .button {
        display: inline-block;
        background: #10b981;
        color: #ffffff;
        padding: 0.75rem 1.5rem;
        border-radius: 0.5rem;
        font-weight: 600;
        text-decoration: none;
        transition: background 0.2s;
        margin-top: 1rem;
      }
      .button:hover {
        background: #059669;
      }
      @keyframes scaleIn {
        from { transform: scale(0.5); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="logo">🎉</div>
      <h1>Google Drive Connected!</h1>
      <p>LifeLogr has successfully authenticated and connected to your Google Drive account.</p>
      <p>Your sync configurations are updated. You can now close this tab and return to writing.</p>
    </div>
  </body>
</html>
"""

_ERROR_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
  <head>
    <title>Connection Failed</title>
    <style>
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #0f172a;
        color: #f8fafc;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100vh;
        margin: 0;
      }
      .card {
        text-align: center;
        background: #1e293b;
        padding: 3rem;
        border-radius: 1.5rem;
        box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
        max-width: 450px;
        border: 1px solid #ef4444;
      }
      h1 {
        color: #ef4444;
        margin-top: 0;
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
      }
      p {
        color: #94a3b8;
        font-size: 1rem;
        line-height: 1.6;
        margin-bottom: 1.5rem;
      }
      .logo {
        font-size: 4.5rem;
        margin-bottom: 1.5rem;
      }
      .error-details {
        background: #0f172a;
        padding: 1rem;
        border-radius: 0.5rem;
        font-family: monospace;
        font-size: 0.875rem;
        color: #f87171;
        word-break: break-all;
        text-align: left;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="logo">❌</div>
      <h1>Authentication Failed</h1>
      <p>We encountered an error while trying to connect your Google Drive account.</p>
      <div class="error-details">{{DETAIL}}</div>
    </div>
  </body>
</html>
"""
