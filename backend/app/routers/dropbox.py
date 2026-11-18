"""Dropbox OAuth 2.0 route handlers.

Exchange/upsert/render plumbing is shared via ``app.routers._oauth_helpers``.
"""

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

router = APIRouter(prefix="/api/v1/backup/dropbox", tags=["backup-dropbox"])

AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Generate the Dropbox OAuth consent URL (offline access for refresh token)."""
    redirect_uri = loopback_redirect_uri(request, "/api/v1/backup/dropbox/callback")
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "dropbox"))
    config = result.scalar_one_or_none()
    client_id = settings.DROPBOX_CLIENT_ID
    stored = load_stored_credentials(config, "Dropbox")
    if stored.get("client_id"):
        client_id = stored["client_id"]
    if not client_id:
        raise HTTPException(status_code=400, detail="Dropbox OAuth client_id is not configured")

    state, _code_verifier, code_challenge = _state.issue_with_pkce()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "token_access_type": "offline",  # required to receive a refresh token
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None, description="OAuth error from Dropbox"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the Dropbox auth code for tokens and save the config."""
    return await oauth_callback_flow(
        request,
        db,
        _state,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
        provider="dropbox",
        label="Dropbox",
        token_url=TOKEN_URL,
        redirect_path="/api/v1/backup/dropbox/callback",
        default_client_id=settings.DROPBOX_CLIENT_ID,
        default_client_secret=settings.DROPBOX_CLIENT_SECRET,
        default_expires_in=14400,  # 4 h, used when the response omits expires_in
        missing_refresh_message="No refresh token returned. Ensure the app uses long-lived access.",
        success_title="Dropbox Connected!",
        success_message="LifeLogr is now connected to your Dropbox account.",
    )
