"""Google Calendar+Tasks+Contacts sync route handlers (OAuth connect, sync, status)."""

from __future__ import annotations

import html
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import OAuthStateStore
from app.core.security import decrypt, encrypt
from app.models.backup import BackupConfig
from app.models.google_sync import GoogleSyncAccount
from app.services.google_oauth import build_auth_url, exchange_code
from app.services.google_sync_service import GoogleSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/google", tags=["google-sync"])
_state = OAuthStateStore()


class GoogleToggles(BaseModel):
    calendar_enabled: bool | None = None
    tasks_enabled: bool | None = None
    contacts_enabled: bool | None = None


class GoogleClientCredentials(BaseModel):
    client_id: str
    client_secret: str


async def _resolve_client_creds(db: AsyncSession) -> tuple[str, str]:
    """Google OAuth client_id/secret: DB-stored app config first, then env.

    Mirrors ``routers/google_drive.py``: a ``BackupConfig(provider="google_sync")``
    row holds an encrypted ``{client_id, client_secret}`` blob the user pasted in
    Settings; if absent, fall back to ``GOOGLE_CLIENT_ID/SECRET`` env vars (dev).
    """
    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    config = (
        await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_sync"))
    ).scalar_one_or_none()
    if config is not None:
        try:
            stored = json.loads(decrypt(config.credentials_encrypted))
            client_id = stored.get("client_id") or client_id
            client_secret = stored.get("client_secret") or client_secret
        except Exception:
            logger.warning("Failed to decrypt stored Google sync client creds", exc_info=True)
    return client_id, client_secret


@router.get("/client-credentials")
async def get_client_credentials(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Whether Google OAuth client credentials are configured. Never returns the secret."""
    client_id, _secret = await _resolve_client_creds(db)
    return {"configured": bool(client_id), "client_id": client_id or None}


@router.put("/client-credentials")
async def set_client_credentials(
    body: GoogleClientCredentials, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Store the Google OAuth client_id/secret (encrypted) for Calendar/Tasks/Contacts sync."""
    client_id = body.client_id.strip()
    client_secret = body.client_secret.strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="client_id and client_secret are required")
    payload = json.dumps({"client_id": client_id, "client_secret": client_secret})
    config = (
        await db.execute(select(BackupConfig).where(BackupConfig.provider == "google_sync"))
    ).scalar_one_or_none()
    if config is None:
        config = BackupConfig(provider="google_sync", credentials_encrypted=encrypt(payload))
        db.add(config)
    else:
        config.credentials_encrypted = encrypt(payload)
    await db.commit()
    return {"configured": True, "client_id": client_id}


@router.get("/auth-url")
async def get_auth_url(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Generate the Google OAuth consent URL (calendar + tasks + contacts scopes)."""
    client_id, _secret = await _resolve_client_creds(db)
    if not client_id:
        raise HTTPException(status_code=400, detail="Google OAuth client_id is not configured")
    # Reconcile the scheduler in case a reconnect flips an account back on.
    from app.services.scheduler_service import SchedulerService

    await SchedulerService.sync_google()
    return {"auth_url": build_auth_url(client_id, _state.issue())}


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Handle the OAuth loopback redirect: exchange code, store the connection."""
    if not _state.consume(state):
        return _render("Authentication Failed", "Invalid or expired OAuth state.", ok=False)

    try:
        client_id, client_secret = await _resolve_client_creds(db)
        if not client_id or not client_secret:
            return _render(
                "Authentication Failed",
                "Google OAuth client_id/secret are not configured. Add them in Settings → Google.",
                ok=False,
            )
        creds = await exchange_code(code, client_id, client_secret)
    except Exception as exc:  # noqa: BLE001 — surface any exchange failure to the user
        return _render("Authentication Failed", str(exc), ok=False)

    # Best-effort: record the connected account's email for display.
    google_email: str | None = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds['access_token']}"},
                timeout=10.0,
            )
            if r.status_code == 200:
                google_email = r.json().get("email")
    except Exception:
        logger.warning("Failed to fetch Google userinfo", exc_info=True)

    encrypted = encrypt(json.dumps(creds))
    account = (await db.execute(select(GoogleSyncAccount))).scalars().first()
    if account is None:
        account = GoogleSyncAccount(credentials_encrypted=encrypted, google_email=google_email)
        db.add(account)
    else:
        account.credentials_encrypted = encrypted
        account.google_email = google_email or account.google_email
        account.last_sync_error = None
    await db.commit()

    # Register the recurring sync job now that an account exists.
    from app.services.scheduler_service import SchedulerService

    await SchedulerService.sync_google()
    return _render("Google Connected", "Calendar, Tasks and Contacts sync is ready.", ok=True)


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Connection + last-sync state for the Settings panel."""
    account = (await db.execute(select(GoogleSyncAccount))).scalars().first()
    if account is None:
        return {"connected": False}
    return {
        "connected": True,
        "google_email": account.google_email,
        "calendar_enabled": account.calendar_enabled,
        "tasks_enabled": account.tasks_enabled,
        "contacts_enabled": account.contacts_enabled,
        "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
        "last_sync_error": account.last_sync_error,
    }


@router.post("/sync")
async def sync_now(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run a two-way Calendar+Tasks+Contacts sync immediately."""
    if (await db.execute(select(GoogleSyncAccount))).scalars().first() is None:
        raise HTTPException(status_code=404, detail="Google account not connected")
    return await GoogleSyncService(db).sync_all()


@router.patch("")
async def update_toggles(
    toggles: GoogleToggles, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Enable/disable Calendar/Tasks/Contacts sync independently."""
    account = (await db.execute(select(GoogleSyncAccount))).scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Google account not connected")
    if toggles.calendar_enabled is not None:
        account.calendar_enabled = toggles.calendar_enabled
    if toggles.tasks_enabled is not None:
        account.tasks_enabled = toggles.tasks_enabled
    if toggles.contacts_enabled is not None:
        account.contacts_enabled = toggles.contacts_enabled
    await db.commit()
    return {
        "calendar_enabled": account.calendar_enabled,
        "tasks_enabled": account.tasks_enabled,
        "contacts_enabled": account.contacts_enabled,
    }


@router.delete("")
async def disconnect(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Remove the Google connection (credentials + cursors)."""
    account = (await db.execute(select(GoogleSyncAccount))).scalars().first()
    if account is not None:
        await db.delete(account)
        await db.commit()
    from app.services.scheduler_service import SchedulerService

    await SchedulerService.sync_google()  # removes the recurring job
    return {"disconnected": True}


def _render(title: str, detail: str, *, ok: bool) -> HTMLResponse:
    color = "#10b981" if ok else "#ef4444"
    emoji = "✅" if ok else "❌"
    return HTMLResponse(
        content=f"""<!DOCTYPE html><html><head><title>{html.escape(title)}</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#f8fafc;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;background:#1e293b;padding:3rem;border-radius:1.5rem;max-width:450px;
border:1px solid {color}}}h1{{color:{color};margin-top:0}}p{{color:#94a3b8}}</style></head>
<body><div class="card"><div style="font-size:4.5rem">{emoji}</div>
<h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>
<p style="font-size:.85rem;color:#64748b">You can close this tab and return to LifeLogr.</p>
</div></body></html>""",
        status_code=200 if ok else 400,
    )
