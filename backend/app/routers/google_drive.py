"""Google Drive OAuth 2.0 route handlers."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import OAuthStateStore
from app.models.backup import BackupConfig
from app.routers._oauth_helpers import (
    load_stored_credentials,
    loopback_redirect_uri,
    oauth_callback_flow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backup/google-drive", tags=["backup-google-drive"])

_state = OAuthStateStore()


def get_default_credentials() -> tuple[str, str]:
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


@router.get("/auth-url")
async def get_auth_url(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Generate Google Drive OAuth consent screen URL."""
    redirect_uri = loopback_redirect_uri(request, "/api/v1/backup/google-drive/callback")
    # Look for existing custom client config in database
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_drive"))
    config = result.scalar_one_or_none()

    default_id, _ = get_default_credentials()
    client_id = default_id
    stored = load_stored_credentials(config, "Google")
    if stored.get("client_id"):
        client_id = stored["client_id"]

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
    state, _code_verifier, code_challenge = _state.issue_with_pkce()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    return {"auth_url": f"{auth_base_url}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = Query(None, description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state token"),
    error: str | None = Query(None, description="OAuth error from Google"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle Google OAuth 2.0 loopback redirection, exchange code, and save tokens."""
    default_id, default_secret = get_default_credentials()
    return await oauth_callback_flow(
        request,
        db,
        _state,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
        provider="google_drive",
        label="Google",
        token_url="https://oauth2.googleapis.com/token",
        redirect_path="/api/v1/backup/google-drive/callback",
        default_client_id=default_id,
        default_client_secret=default_secret,
        # prompt=consent didn't fire / first-time sync — ask the user to retry.
        missing_refresh_message="No refresh token returned. Please disconnect and try again.",
        success_title="Google Drive Connected!",
        success_message="LifeLogr is now connected to your Google Drive account.",
    )
