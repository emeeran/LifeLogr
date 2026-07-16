"""Orchestrates two-way Google Calendar + Tasks sync for the connected account.

Loads the single ``GoogleSyncAccount``, builds a ``GoogleAPIClient`` whose
token-refresh callback persists refreshed tokens, then runs Calendar then Tasks
sync — each in its own try/except so one failing service doesn't abort the
other (mirroring ``EmailSyncService.sync_all_accounts``). Never raises.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.models.google_sync import GoogleSyncAccount
from app.services.calendar_sync_service import CalendarSyncService
from app.services.google_oauth import GoogleAPIClient
from app.services.tasks_sync_service import TasksSyncService

logger = logging.getLogger(__name__)


class GoogleSyncService:
    """Runs Calendar + Tasks sync for the connected Google account."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_account(self) -> GoogleSyncAccount | None:
        result = await self.db.execute(select(GoogleSyncAccount))
        return result.scalars().first()

    async def sync_all(self) -> dict[str, Any]:
        """Sync Calendar + Tasks; return a per-service summary. Never raises."""
        account = await self._get_account()
        if account is None:
            return {"skipped": "not connected"}

        try:
            creds = json.loads(decrypt(account.credentials_encrypted))
        except Exception:
            logger.warning("Failed to decrypt Google credentials", exc_info=True)
            account.last_sync_error = "Credential decryption failed"
            await self.db.commit()
            return {"error": "credential decryption failed"}

        async def on_refresh(access_token: str, token_expiry: str) -> None:
            creds["access_token"] = access_token
            creds["token_expiry"] = token_expiry
            account.credentials_encrypted = encrypt(json.dumps(creds))
            await self.db.commit()

        result: dict[str, Any] = {"calendar": None, "tasks": None}
        errors: list[str] = []
        async with GoogleAPIClient(creds, on_token_refresh=on_refresh) as api:
            try:
                result["calendar"] = await CalendarSyncService(self.db, account, api).sync()
            except Exception as exc:
                logger.warning("Calendar sync failed", exc_info=True)
                errors.append(f"calendar: {exc}")
                result["calendar"] = {"error": str(exc)}
            try:
                result["tasks"] = await TasksSyncService(self.db, account, api).sync()
            except Exception as exc:
                logger.warning("Tasks sync failed", exc_info=True)
                errors.append(f"tasks: {exc}")
                result["tasks"] = {"error": str(exc)}

        account.last_synced_at = datetime.now()
        account.last_sync_error = "; ".join(errors) if errors else None
        await self.db.commit()
        return result
