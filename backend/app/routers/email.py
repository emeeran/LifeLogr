"""Email route handlers — accounts, folders, IMAP sync, messages, compose."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import MediaSizeError
from app.core.database import get_db
from app.schemas.email import (
    EmailAccountCreate,
    EmailAccountResponse,
    EmailAccountTestResult,
    EmailAccountUpdate,
    EmailAttachmentResponse,
    EmailCompose,
    EmailFolderResponse,
    EmailFolderUpdate,
    EmailMessageListResponse,
    EmailMessageListResult,
    EmailMessageResponse,
    EmailSendResult,
    MessageFlagUpdate,
    MessageSpamUpdate,
    SpamRuleCreate,
    SpamRuleResponse,
    TempAttachmentResponse,
)
from app.services.email_service import (
    EmailAccountService,
    EmailComposeService,
    EmailMessageService,
    EmailSyncService,
    store_temp_attachment,
)
from app.services.spam_service import SpamService

router = APIRouter(prefix="/api/v1/email", tags=["email"])


def _message_response(message: Any, attachments: list[Any]) -> EmailMessageResponse:
    """Build a full message response, attaching the fetched attachment rows."""
    resp = EmailMessageResponse.model_validate(message)
    resp.attachments = [EmailAttachmentResponse.model_validate(a) for a in attachments]
    return resp


# ── Accounts ───────────────────────────────────────────────────────────────


@router.get("/accounts", response_model=list[EmailAccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)) -> Any:
    """List all active email accounts."""
    svc = EmailAccountService(db)
    return await svc.list_all()


@router.post("/accounts", response_model=EmailAccountResponse, status_code=201)
async def create_account(data: EmailAccountCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Add an IMAP/SMTP mailbox (password encrypted before storage)."""
    svc = EmailAccountService(db)
    return await svc.create(data)


@router.get("/accounts/{account_id}", response_model=EmailAccountResponse)
async def get_account(account_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = EmailAccountService(db)
    return await svc.get(account_id)


@router.put("/accounts/{account_id}", response_model=EmailAccountResponse)
async def update_account(
    account_id: int, data: EmailAccountUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = EmailAccountService(db)
    return await svc.update(account_id, data)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = EmailAccountService(db)
    await svc.delete(account_id)


@router.post("/accounts/{account_id}/test", response_model=EmailAccountTestResult)
async def test_account(account_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Open & close an IMAP connection to verify the credentials work."""
    svc = EmailAccountService(db)
    result = await svc.test_connection(account_id)
    return EmailAccountTestResult(success=bool(result["success"]), error=result["error"])


@router.post("/accounts/{account_id}/sync")
async def sync_account(account_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Discover folders and pull new messages for one account."""
    svc = EmailSyncService(db)
    new_count = await svc.sync_account(account_id)
    return {"new_messages": new_count}


# ── Folders ────────────────────────────────────────────────────────────────


@router.get("/accounts/{account_id}/folders", response_model=list[EmailFolderResponse])
async def list_folders(account_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """List cached folders for an account."""
    svc = EmailAccountService(db)
    return await svc.list_folders(account_id)


@router.post("/accounts/{account_id}/folders/refresh", response_model=list[EmailFolderResponse])
async def refresh_folders(account_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Re-query the server's folder list and upsert any new folders."""
    svc = EmailAccountService(db)
    return await svc.discover_folders(account_id)


@router.patch("/folders/{folder_id}", response_model=EmailFolderResponse)
async def update_folder(
    folder_id: int, data: EmailFolderUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = EmailAccountService(db)
    return await svc.update_folder(
        folder_id, sync_enabled=data.sync_enabled, display_name=data.display_name
    )


# ── Sync all ───────────────────────────────────────────────────────────────


@router.post("/sync")
async def sync_all(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Sync every active, sync-enabled account (used by the scheduler too)."""
    svc = EmailSyncService(db)
    await svc.sync_all_accounts()
    return {"synced": True}


# ── Messages ───────────────────────────────────────────────────────────────
# NOTE: static sub-paths must be declared before the /messages/{id} wildcard.


@router.get("/messages", response_model=EmailMessageListResult)
async def list_messages(
    account_id: int | None = Query(default=None),
    folder_id: int | None = Query(default=None),
    unread_only: bool = Query(default=False),
    starred_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    exclude_spam: bool = Query(default=True),
    spam_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = EmailMessageService(db)
    items, total = await svc.list_messages(
        account_id=account_id,
        folder_id=folder_id,
        unread_only=unread_only,
        starred_only=starred_only,
        search=search,
        exclude_spam=exclude_spam,
        spam_only=spam_only,
        offset=offset,
        limit=limit,
    )
    return EmailMessageListResult(
        items=[EmailMessageListResponse.model_validate(m) for m in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/messages/bulk-delete", status_code=204)
async def bulk_delete_messages(
    ids: list[int], db: AsyncSession = Depends(get_db)
) -> None:
    """Soft/move-delete multiple messages at once."""
    svc = EmailMessageService(db)
    await svc.bulk_delete(ids)


@router.get("/messages/{message_id}", response_model=EmailMessageResponse)
async def get_message(message_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    svc = EmailMessageService(db)
    result = await svc.get_message(message_id)
    return _message_response(result["message"], result["attachments"])


@router.patch("/messages/{message_id}/flags", response_model=EmailMessageListResponse)
async def update_message_flags(
    message_id: int, data: MessageFlagUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    svc = EmailMessageService(db)
    message = await svc.set_flags(message_id, data.is_read, data.is_starred)
    return EmailMessageListResponse.model_validate(message)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(message_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = EmailMessageService(db)
    await svc.delete_message(message_id)


@router.patch("/messages/{message_id}/spam", response_model=EmailMessageListResponse)
async def update_message_spam(
    message_id: int, data: MessageSpamUpdate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Mark a message as spam / not-spam (user override + blocklist sync)."""
    svc = EmailMessageService(db)
    message = await svc.mark_spam(message_id, data.is_spam)
    return EmailMessageListResponse.model_validate(message)


@router.get("/messages/{message_id}/attachments/{attachment_id}")
async def download_attachment(
    message_id: int, attachment_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    svc = EmailMessageService(db)
    path = await svc.attachment_path(message_id, attachment_id)
    # Re-fetch the filename/content_type for headers.
    from sqlalchemy import select

    from app.models.email_attachment import EmailAttachment

    att = (
        await db.execute(
            select(EmailAttachment).where(EmailAttachment.id == attachment_id)
        )
    ).scalar_one_or_none()
    filename = att.filename if att else path.name
    media_type = att.content_type if att else "application/octet-stream"
    return FileResponse(path, filename=filename, media_type=media_type)


@router.get("/messages/{message_id}/raw")
async def download_raw_message(
    message_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    svc = EmailMessageService(db)
    path = await svc.raw_path(message_id)
    return FileResponse(path, filename=f"message_{message_id}.eml", media_type="message/rfc822")


# ── Spam filter (blocklist + rescore) ───────────────────────────────────────


@router.get("/spam/rules", response_model=list[SpamRuleResponse])
async def list_spam_rules(db: AsyncSession = Depends(get_db)) -> Any:
    """List blocked senders / domains."""
    return await SpamService(db).list_rules()


@router.post("/spam/rules", response_model=SpamRuleResponse, status_code=201)
async def create_spam_rule(
    data: SpamRuleCreate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Block a sender address (is_domain=false) or domain (is_domain=true)."""
    return await SpamService(db).add_rule(data.pattern, data.is_domain)


@router.delete("/spam/rules/{rule_id}", status_code=204)
async def delete_spam_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await SpamService(db).remove_rule(rule_id)


@router.post("/spam/rescore")
async def rescore_spam(
    account_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Recompute heuristic spam scores (respects user overrides + blocklist)."""
    changed = await SpamService(db).rescore(account_id)
    return {"rescored": changed}


# ── Compose ────────────────────────────────────────────────────────────────


@router.post("/compose/send", response_model=EmailSendResult)
async def send_message(data: EmailCompose, db: AsyncSession = Depends(get_db)) -> Any:
    svc = EmailComposeService(db)
    result = await svc.send(data)
    return EmailSendResult(**result)


@router.post("/compose/draft", response_model=EmailSendResult)
async def save_draft(data: EmailCompose, db: AsyncSession = Depends(get_db)) -> Any:
    svc = EmailComposeService(db)
    result = await svc.save_draft(data)
    return EmailSendResult(**result)


@router.post("/attachments", response_model=TempAttachmentResponse)
async def upload_temp_attachment(file: UploadFile = File(...)) -> Any:
    """Stage an attachment for an outgoing message; returns a temp id.

    The temp id is referenced in ``EmailCompose.attachment_ids`` and consumed
    (file deleted) once the message is sent or saved as a draft.
    """
    payload = await file.read()
    if len(payload) > settings.EMAIL_MAX_ATTACHMENT_SIZE_BYTES:
        raise MediaSizeError("Attachment exceeds the size limit")
    meta = store_temp_attachment(
        filename=file.filename or "attachment",
        content_type=file.content_type or "application/octet-stream",
        payload=payload,
    )
    return TempAttachmentResponse(**meta)
