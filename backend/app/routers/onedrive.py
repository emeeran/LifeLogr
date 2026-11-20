"""OneDrive (Microsoft Graph) OAuth 2.0 route handlers.

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

router = APIRouter(prefix="/api/v1/backup/onedrive", tags=["backup-onedrive"])

SCOPES = "Files.ReadWrite.AppFolder offline_access"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the OneDrive OAuth consent URL."""
    redirect_uri = loopback_redirect_uri(request, "/api/v1/backup/onedrive/callback")
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "onedrive"))
    config = result.scalar_one_or_none()
    client_id = settings.ONEDRIVE_CLIENT_ID
    stored = load_stored_credentials(config, "OneDrive")
    if stored.get("client_id"):
        client_id = stored["client_id"]
    if not client_id:
        raise HTTPException(status_code=400, detail="OneDrive OAuth client_id is not configured")

    state, _code_verifier, code_challenge = _state.issue_with_pkce()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
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
    error: str | None = Query(None, description="OAuth error from Microsoft"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the OneDrive auth code for tokens and save the config."""
    return await oauth_callback_flow(
        request,
        db,
        _state,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
        provider="onedrive",
        label="OneDrive",
        token_url=TOKEN_URL,
        redirect_path="/api/v1/backup/onedrive/callback",
        default_client_id=settings.ONEDRIVE_CLIENT_ID,
        default_client_secret=settings.ONEDRIVE_CLIENT_SECRET,
        extra_exchange_data={"scope": SCOPES},
        success_title="OneDrive Connected!",
        success_message="LifeLogr is now connected to your OneDrive account.",
    )
