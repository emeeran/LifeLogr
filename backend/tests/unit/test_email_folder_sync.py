"""Tests for EmailSyncService.sync_folder non-selectable-folder handling."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.email_account import EmailAccount
from app.models.email_folder import EmailFolder
from app.services.email_service import EmailSyncService


def _account() -> EmailAccount:
    return EmailAccount(
        label="t",
        email_address="a@b.c",
        imap_host="h",
        imap_port=993,
        imap_use_ssl=True,
        smtp_host="h",
        smtp_port=587,
        smtp_use_tls=True,
        username="a@b.c",
        password_encrypted="x",
    )


@pytest.mark.asyncio
async def test_nonexistent_folder_is_auto_disabled(db_session) -> None:
    acct = _account()
    db_session.add(acct)
    await db_session.commit()

    folder = EmailFolder(account_id=acct.id, folder_name="[Gmail]", sync_enabled=True)
    db_session.add(folder)
    await db_session.commit()

    imap = AsyncMock()
    imap.select.side_effect = RuntimeError(
        "IMAP SELECT '[Gmail]' failed: [b'[NONEXISTENT] Unknown Mailbox: [Gmail] (Failure)']"
    )

    result = await EmailSyncService(db_session).sync_folder(imap, acct, folder)

    assert result == 0  # nothing synced
    # Marked disabled (sync_account persists it via its per-folder commit).
    assert folder.sync_enabled is False


@pytest.mark.asyncio
async def test_other_select_error_propagates_unchanged(db_session) -> None:
    acct = _account()
    db_session.add(acct)
    await db_session.commit()
    folder = EmailFolder(account_id=acct.id, folder_name="INBOX", sync_enabled=True)
    db_session.add(folder)
    await db_session.commit()

    imap = AsyncMock()
    imap.select.side_effect = RuntimeError("IMAP SELECT 'INBOX' failed: connection lost")

    with pytest.raises(RuntimeError):
        await EmailSyncService(db_session).sync_folder(imap, acct, folder)
    # A genuine error does NOT silently disable the folder.
    await db_session.refresh(folder)
    assert folder.sync_enabled is True
