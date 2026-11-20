"""Box OAuth 2.0 route handlers — mirrors google_drive.py.

Loopback flow: /auth-url builds the Box consent URL; Box redirects to the
request-derived loopback callback URI, /callback exchanges the code for tokens
and upserts a BackupConfig(provider="box"). Box rotates its refresh token, so
the stored creds are rewritten whenever BackupService refreshes (see
BoxProvider).

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

router = APIRouter(prefix="/api/v1/backup/box", tags=["backup-box"])

AUTHORIZE_URL = "https://account.box.com/api/oauth2/authorize"
TOKEN_URL = "https://api.box.com/oauth2/token"
_state = OAuthStateStore()


@router.get("/auth-url")
async def get_auth_url(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the Box OAuth consent screen URL."""
    redirect_uri = loopback_redirect_uri(request, "/api/v1/backup/box/callback")
    result = await db.execute(select(BackupConfig).where(BackupConfig.provider == "box"))
    config = result.scalar_one_or_none()

    client_id = settings.BOX_CLIENT_ID
    stored = load_stored_credentials(config, "Box")
    if stored.get("client_id"):
        client_id = stored["client_id"]

    if not client_id:
        raise HTTPException(status_code=400, detail="Box OAuth client_id is not configured")

    state, _code_verifier, code_challenge = _state.issue_with_pkce()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return {"auth_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: str | None = Query(None, description="Authorization code from Box"),
    state: str | None = Query(None, description="OAuth state token"),
    error: str | None = Query(None, description="OAuth error from Box"),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the Box OAuth loopback redirect: exchange code, save tokens."""
    return await oauth_callback_flow(
        request,
        db,
        _state,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
        provider="box",
        label="Box",
        token_url=TOKEN_URL,
        redirect_path="/api/v1/backup/box/callback",
        default_client_id=settings.BOX_CLIENT_ID,
        default_client_secret=settings.BOX_CLIENT_SECRET,
        # Box rotates refresh tokens, so only a fresh one from this exchange is
        # good enough — a stored fallback would be stale by design.
        allow_stored_refresh_token=False,
        missing_refresh_message="No refresh token returned by Box. Please retry.",
        exchange_timeout=15.0,
        success_title="Box Connected!",
        success_message="LifeLogr is now connected to your Box account.",
    )
