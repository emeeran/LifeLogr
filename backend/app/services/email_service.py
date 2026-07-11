"""Email services — account management, IMAP sync, message ops, compose/send."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.email_account import EmailAccount
from app.models.email_attachment import EmailAttachment
from app.models.email_folder import EmailFolder
from app.models.email_message import EmailMessage
from app.schemas.email import (
    EmailAccountCreate,
    EmailAccountUpdate,
    EmailCompose,
)
from app.services.contact_service import ContactService
from app.services.email_protocol import (
    ImapClient,
    ParsedAttachment,
    ParsedMessage,
    normalize_email,
    parse_message,
    send_via_smtp,
)
from app.services.spam_service import SpamService, _domain_of

logger = logging.getLogger(__name__)

# Special-use detection from IMAP LIST flags / folder names.
_SPECIAL_USE_FLAGS = {
    "\\Inbox": "inbox",
    "\\Sent": "sent",
    "\\Drafts": "drafts",
    "\\Trash": "trash",
    "\\Junk": "junk",
    "\\Archive": "archive",
}
_FOLDER_NAME_HINTS = {
    "inbox": "inbox",
    "sent": "sent",
    "drafts": "drafts",
    "trash": "trash",
    "junk": "junk",
    "spam": "junk",
    "archive": "archive",
}

# In-memory temp-attachment registry for compose (single-process desktop app).
# {temp_id: {"path": Path, "filename": str, "content_type": str, "size": int}}
_TEMP_ATTACHMENTS: dict[str, dict] = {}


def _special_use(folder_name: str, flags: str) -> str | None:
    for token, label in _SPECIAL_USE_FLAGS.items():
        if token.lower() in flags.lower():
            return label
    lower = folder_name.lower().strip().replace("[gmail]/", "")
    return _FOLDER_NAME_HINTS.get(lower)


def _account_media_dir(account_id: int) -> Path:
    d = Path(settings.MEDIA_DIR) / "email" / str(account_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(filename: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    return safe[:80] or "attachment"


def _exc_message(exc: BaseException) -> str:
    """Human-readable exception text for UI surfaces.

    ``imaplib`` raises errors whose args are ``bytes`` (e.g.
    ``b'[ALERT] Application-specific password required'``), so a plain
    ``str(exc)`` surfaces an ugly ``b'...'`` literal. Decode any bytes args.
    """
    parts: list[str] = []
    for arg in getattr(exc, "args", None) or (str(exc),):
        if isinstance(arg, (bytes, bytearray)):
            parts.append(bytes(arg).decode("utf-8", "replace"))
        else:
            parts.append(str(arg))
    msg = " ".join(p for p in parts if p).strip()
    return msg or str(exc)


# ── Background IMAP side-effects ────────────────────────────────────────────
# Flag pushes and move-to-trash are slow (a full IMAP round-trip each) and the
# local DB is the source of truth for the UI. We perform the fast DB write in
# the request, return immediately, and let these fire-and-forget coroutines
# sync the change to the server afterwards. Each opens its OWN session so it
# outlives the request that scheduled it.


async def push_flags_background(
    message_id: int, is_read: bool | None, is_starred: bool | None
) -> None:
    """Mirror a flag change to IMAP after the response is sent."""
    try:
        from app.core.database import async_session

        async with async_session() as db:
            await EmailMessageService(db)._push_flags_to_imap_for(message_id, is_read, is_starred)
    except Exception:  # noqa: BLE001
        logger.debug("Background flag push failed for message %s", message_id, exc_info=True)


async def move_to_trash_background(account_id: int, moves: list[tuple[str, int]]) -> None:
    """Best-effort server-side move of already-locally-deleted messages.

    ``moves`` is a list of ``(source_folder_name, uid)``. The messages are
    already gone from the DB; this only syncs the mailbox so the server Inbox
    doesn't keep copies. Grouped by source folder to minimise SELECTs.
    """
    if not moves:
        return
    try:
        from app.core.database import async_session

        async with async_session() as db:
            account = (
                await db.execute(select(EmailAccount).where(EmailAccount.id == account_id))
            ).scalar_one_or_none()
            if not account:
                return
            trash_name = await _special_folder_name(db, account_id, "trash")
            if not trash_name:
                return
            password = security.decrypt(account.password_encrypted)

        by_folder: dict[str, list[int]] = {}
        for folder_name, uid in moves:
            by_folder.setdefault(folder_name, []).append(uid)
        async with ImapClient(
            account.imap_host,
            account.imap_port,
            account.imap_use_ssl,
            account.username,
            password,
        ) as imap:
            for folder_name, uids in by_folder.items():
                try:
                    await imap.select(folder_name)
                    for uid in uids:
                        await imap.uid_move(uid, trash_name)
                except Exception:  # noqa: BLE001
                    logger.debug("Trash move failed in %s", folder_name, exc_info=True)
    except Exception:  # noqa: BLE001
        logger.debug("Background trash move failed for account %s", account_id, exc_info=True)


async def move_to_junk_background(account_id: int, moves: list[tuple[str, int]]) -> None:
    """Best-effort server-side move of messages into the Junk folder."""
    if not moves:
        return
    try:
        from app.core.database import async_session

        async with async_session() as db:
            account = (
                await db.execute(select(EmailAccount).where(EmailAccount.id == account_id))
            ).scalar_one_or_none()
            if not account:
                return
            junk_name = await _special_folder_name(db, account_id, "junk")
            if not junk_name:
                return
            password = security.decrypt(account.password_encrypted)

        by_folder: dict[str, list[int]] = {}
        for folder_name, uid in moves:
            by_folder.setdefault(folder_name, []).append(uid)
        async with ImapClient(
            account.imap_host,
            account.imap_port,
            account.imap_use_ssl,
            account.username,
            password,
        ) as imap:
            for folder_name, uids in by_folder.items():
                try:
                    await imap.select(folder_name)
                    for uid in uids:
                        await imap.uid_move(uid, junk_name)
                except Exception:  # noqa: BLE001
                    logger.debug("Junk move failed in %s", folder_name, exc_info=True)
    except Exception:  # noqa: BLE001
        logger.debug("Background junk move failed for account %s", account_id, exc_info=True)


async def _special_folder_name(db: AsyncSession, account_id: int, special: str) -> str | None:
    """Resolve the IMAP name of a special-use folder (trash/junk) if any."""
    folder = (
        (
            await db.execute(
                select(EmailFolder).where(
                    EmailFolder.account_id == account_id,
                    EmailFolder.special_use == special,
                )
            )
        )
        .scalars()
        .first()
    )
    return folder.folder_name if folder else None


# ── Account service ────────────────────────────────────────────────────────


class EmailAccountService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: EmailAccountCreate) -> EmailAccount:
        account = EmailAccount(
            label=data.label,
            email_address=normalize_email(str(data.email_address)),
            imap_host=data.imap_host,
            imap_port=data.imap_port,
            imap_use_ssl=data.imap_use_ssl,
            smtp_host=data.smtp_host,
            smtp_port=data.smtp_port,
            smtp_use_tls=data.smtp_use_tls,
            username=data.username,
            password_encrypted=security.encrypt(data.password),
            display_name=data.display_name,
            poll_interval_minutes=data.poll_interval_minutes,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        await self._reschedule_jobs()
        return account

    async def list_all(self) -> list[EmailAccount]:
        return list(
            (
                await self.db.execute(
                    select(EmailAccount)
                    .where(EmailAccount.is_active == True)  # noqa: E712
                    .order_by(EmailAccount.label)
                )
            )
            .scalars()
            .all()
        )

    async def get(self, account_id: int) -> EmailAccount:
        account = (
            await self.db.execute(select(EmailAccount).where(EmailAccount.id == account_id))
        ).scalar_one_or_none()
        if not account:
            raise NotFoundError(f"Email account {account_id} not found")
        return account

    async def update(self, account_id: int, data: EmailAccountUpdate) -> EmailAccount:
        account = await self.get(account_id)
        for field_name in (
            "label",
            "imap_host",
            "imap_port",
            "imap_use_ssl",
            "smtp_host",
            "smtp_port",
            "smtp_use_tls",
            "display_name",
            "sync_enabled",
            "poll_interval_minutes",
            "is_active",
        ):
            val = getattr(data, field_name)
            if val is not None:
                setattr(account, field_name, val)
        if data.email_address is not None:
            account.email_address = normalize_email(str(data.email_address))
        if data.username is not None:
            account.username = data.username
        if data.password is not None:
            account.password_encrypted = security.encrypt(data.password)
        await self.db.commit()
        await self.db.refresh(account)
        await self._reschedule_jobs()
        return account

    async def delete(self, account_id: int) -> None:
        account = await self.get(account_id)
        await self.db.delete(account)
        await self.db.commit()
        await self._reschedule_jobs()
        # Best-effort cleanup of on-disk message store for this account.
        import shutil

        d = Path(settings.MEDIA_DIR) / "email" / str(account_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    async def test_connection(self, account_id: int) -> dict[str, object]:
        account = await self.get(account_id)
        password = security.decrypt(account.password_encrypted)
        try:
            async with ImapClient(
                account.imap_host,
                account.imap_port,
                account.imap_use_ssl,
                account.username,
                password,
            ) as imap:
                await imap.select("INBOX")
            return {"success": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": _exc_message(exc)}

    async def list_folders(self, account_id: int) -> list[EmailFolder]:
        """Cached folders for an account (no server round-trip)."""
        await self.get(account_id)  # raises NotFoundError if missing
        return await self._folders_for(account_id)

    async def discover_folders(self, account_id: int) -> list[EmailFolder]:
        """LIST folders on the server and upsert EmailFolder rows."""
        account = await self.get(account_id)
        password = security.decrypt(account.password_encrypted)
        async with ImapClient(
            account.imap_host, account.imap_port, account.imap_use_ssl, account.username, password
        ) as imap:
            remote = await imap.list_folders()

        existing = {
            f.folder_name: f
            for f in (
                await self.db.execute(
                    select(EmailFolder).where(EmailFolder.account_id == account_id)
                )
            )
            .scalars()
            .all()
        }
        for name, flags in remote:
            special = _special_use(name, flags)
            if name in existing:
                if special and not existing[name].special_use:
                    existing[name].special_use = special
                continue
            folder = EmailFolder(
                account_id=account_id,
                folder_name=name,
                display_name=name.split("/")[-1],
                special_use=special,
            )
            self.db.add(folder)
        await self.db.commit()
        return await self._folders_for(account_id)

    async def _folders_for(self, account_id: int) -> list[EmailFolder]:
        return list(
            (
                await self.db.execute(
                    select(EmailFolder)
                    .where(EmailFolder.account_id == account_id)
                    .order_by(EmailFolder.folder_name)
                )
            )
            .scalars()
            .all()
        )

    async def update_folder(
        self, folder_id: int, sync_enabled: bool | None, display_name: str | None
    ) -> EmailFolder:
        folder = (
            await self.db.execute(select(EmailFolder).where(EmailFolder.id == folder_id))
        ).scalar_one_or_none()
        if not folder:
            raise NotFoundError(f"Folder {folder_id} not found")
        if sync_enabled is not None:
            folder.sync_enabled = sync_enabled
        if display_name is not None:
            folder.display_name = display_name
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    @staticmethod
    async def _reschedule_jobs() -> None:
        try:
            from app.services.scheduler_service import SchedulerService

            await SchedulerService.sync_email_accounts()
        except Exception:
            logger.debug("Email job resync skipped", exc_info=True)


# ── Sync service ───────────────────────────────────────────────────────────


class EmailSyncService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync_all_accounts(self) -> None:
        """Sync every active, sync-enabled account. Used by the scheduler job."""
        account_ids = [
            a.id
            for a in (
                await self.db.execute(
                    select(EmailAccount).where(
                        EmailAccount.is_active == True,  # noqa: E712
                        EmailAccount.sync_enabled == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        ]
        for account_id in account_ids:
            try:
                await self.sync_account(account_id)
            except Exception:
                logger.exception("Email sync failed for account %s", account_id)

    async def sync_account(self, account_id: int) -> int:
        """Discover folders then sync each enabled one. Returns new message count."""
        account_svc = EmailAccountService(self.db)
        account = await account_svc.get(account_id)
        await account_svc.discover_folders(account_id)
        folders = await account_svc._folders_for(account_id)

        password = security.decrypt(account.password_encrypted)
        new_total = 0
        try:
            async with ImapClient(
                account.imap_host,
                account.imap_port,
                account.imap_use_ssl,
                account.username,
                password,
            ) as imap:
                for folder in folders:
                    if not folder.sync_enabled:
                        continue
                    try:
                        new_total += await self.sync_folder(imap, account, folder)
                    except Exception:
                        logger.exception("Sync failed for folder %s", folder.folder_name)
            account.last_synced_at = datetime.now(timezone.utc)
            account.last_sync_error = None
        except Exception as exc:  # noqa: BLE001
            account.last_sync_error = _exc_message(exc)[:500]
            logger.warning("Account %s sync error: %s", account_id, exc)
            raise
        finally:
            await self.db.commit()
        return new_total

    async def sync_folder(
        self, imap: ImapClient, account: EmailAccount, folder: EmailFolder
    ) -> int:
        count, uidvalidity = await imap.select(folder.folder_name)

        # UIDVALIDITY change → UIDs invalidated; wipe and re-sync.
        if (
            folder.uidvalidity is not None
            and uidvalidity is not None
            and folder.uidvalidity != uidvalidity
        ):
            logger.warning(
                "UIDVALIDITY changed for %s (%d→%d); full re-sync",
                folder.folder_name,
                folder.uidvalidity,
                uidvalidity,
            )
            await self.db.execute(
                select(EmailMessage).where(EmailMessage.folder_id == folder.id)
            )  # load to cascade-delete attachments; executed below
            msgs = (
                (
                    await self.db.execute(
                        select(EmailMessage).where(EmailMessage.folder_id == folder.id)
                    )
                )
                .scalars()
                .all()
            )
            for m in msgs:
                await self.db.delete(m)
            folder.last_uid = 0
        if uidvalidity is not None:
            folder.uidvalidity = uidvalidity

        criteria = f"{folder.last_uid + 1}:*" if folder.last_uid > 0 else "ALL"
        uids = [u for u in await imap.uid_search(criteria) if u > folder.last_uid]
        uids.sort()
        if not uids:
            await self._refresh_folder_counts(folder)
            return 0

        new_count = 0
        batch = settings.EMAIL_INITIAL_SYNC_BATCH
        for uid in uids:
            raw, flags = await imap.uid_fetch_rfc822(uid)
            if not raw:
                continue
            await self._store_message(folder, account, uid, raw, flags)
            folder.last_uid = max(folder.last_uid, uid)
            new_count += 1
            if new_count % batch == 0:
                await self.db.flush()
        await self._refresh_folder_counts(folder)
        return new_count

    async def _refresh_folder_counts(self, folder: EmailFolder) -> None:
        total = (
            await self.db.execute(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.folder_id == folder.id)
            )
        ).scalar() or 0
        unread = (
            await self.db.execute(
                select(func.count())
                .select_from(EmailMessage)
                .where(
                    EmailMessage.folder_id == folder.id,
                    EmailMessage.is_read == False,  # noqa: E712
                )
            )
        ).scalar() or 0
        folder.message_count = int(total)
        folder.unread_count = int(unread)

    async def _store_message(
        self,
        folder: EmailFolder,
        account: EmailAccount,
        uid: int,
        raw: bytes,
        flags: list[str],
    ) -> None:
        # Skip if already stored (idempotent on (folder, uid)).
        exists = (
            await self.db.execute(
                select(EmailMessage.id).where(
                    EmailMessage.folder_id == folder.id, EmailMessage.uid == uid
                )
            )
        ).scalar_one_or_none()
        if exists:
            return

        parsed = parse_message(raw)
        from_addr = parsed.from_address or account.email_address

        # Local spam filter: blocklist → spam, contact allowlist → ham, else heuristic.
        spam_score, is_spam = await SpamService(self.db).classify(parsed)

        # A blocked sender with action="delete" never lands in the app — drop it
        # now (the caller still advances last_uid so it isn't re-fetched).
        addr_lower = from_addr.lower()
        if await SpamService(self.db).block_action(addr_lower, _domain_of(addr_lower)) == "delete":
            return

        # Persist raw .eml
        media_dir = _account_media_dir(account.id)
        eml_rel = f"email/{account.id}/{folder.id}_{uid}.eml"
        (Path(settings.MEDIA_DIR) / eml_rel).write_bytes(raw)

        attachments_meta: list[ParsedAttachment] = []
        has_attachments = False
        for att in parsed.attachments:
            if not att.payload:
                continue
            has_attachments = True
            attachments_meta.append(att)

        flags_lower = [f.lower() for f in flags]
        message = EmailMessage(
            account_id=account.id,
            folder_id=folder.id,
            uid=uid,
            message_id=parsed.message_id,
            in_reply_to=parsed.in_reply_to,
            references=parsed.references,
            from_address=from_addr,
            from_name=parsed.from_name,
            to_addresses=parsed.to_addresses,
            cc_addresses=parsed.cc_addresses or None,
            bcc_addresses=parsed.bcc_addresses or None,
            reply_to=parsed.reply_to,
            subject=parsed.subject,
            text_body=parsed.text_body,
            html_body=parsed.html_body,
            snippet=parsed.snippet,
            sent_at=parsed.sent_at,
            flags=" ".join(flags),
            is_read="\\seen" in flags_lower,
            is_starred="\\flagged" in flags_lower,
            is_draft="\\draft" in flags_lower,
            is_spam=is_spam,
            spam_score=spam_score,
            raw_path=eml_rel,
            has_attachments=has_attachments,
            size_bytes=len(raw),
        )
        self.db.add(message)
        await self.db.flush()

        att_dir = media_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        for att in attachments_meta:
            rel = f"email/{account.id}/attachments/{uuid4().hex}_{_sanitize(att.filename)}"
            (Path(settings.MEDIA_DIR) / rel).write_bytes(att.payload)
            self.db.add(
                EmailAttachment(
                    message_id=message.id,
                    filename=att.filename,
                    content_type=att.content_type,
                    file_size=len(att.payload),
                    content_id=att.content_id,
                    is_inline=att.is_inline,
                    storage_path=rel,
                )
            )

        # Auto-extract contacts from correspondence (skip the account owner).
        await self._extract_contacts(parsed, account)

    async def _extract_contacts(self, parsed: ParsedMessage, account: EmailAccount) -> None:
        owner = account.email_address.lower()
        contact_svc = ContactService(self.db)
        candidates: list[tuple[str | None, str | None]] = []
        if parsed.from_address and parsed.from_address.lower() != owner:
            candidates.append((parsed.from_name, parsed.from_address))
        for entry in parsed.to_addresses + parsed.cc_addresses:
            addr = entry.get("address")
            if addr and addr.lower() != owner:
                candidates.append((entry.get("name"), addr))
        for name, addr in candidates:
            try:
                await contact_svc.upsert_from_email(addr, name, account.id)
            except Exception:
                logger.debug("Contact upsert failed for %s", addr, exc_info=True)


# ── Message service ────────────────────────────────────────────────────────


class EmailMessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_messages(
        self,
        account_id: int | None = None,
        folder_id: int | None = None,
        unread_only: bool = False,
        starred_only: bool = False,
        search: str | None = None,
        exclude_spam: bool = True,
        spam_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[EmailMessage], int]:
        conditions = []
        if account_id is not None:
            conditions.append(EmailMessage.account_id == account_id)
        if folder_id is not None:
            conditions.append(EmailMessage.folder_id == folder_id)
        if unread_only:
            conditions.append(EmailMessage.is_read == False)  # noqa: E712
        if starred_only:
            conditions.append(EmailMessage.is_starred == True)  # noqa: E712
        if spam_only:
            conditions.append(EmailMessage.is_spam == True)  # noqa: E712
        elif exclude_spam:
            conditions.append(EmailMessage.is_spam == False)  # noqa: E712
        if search:
            like = f"%{search.lower()}%"
            conditions.append(
                or_(
                    EmailMessage.subject.ilike(like),
                    EmailMessage.snippet.ilike(like),
                    EmailMessage.from_address.ilike(like),
                    EmailMessage.from_name.ilike(like),
                    EmailMessage.text_body.ilike(like),
                )
            )

        base = select(EmailMessage)
        count_stmt = select(func.count()).select_from(EmailMessage)
        for cond in conditions:
            base = base.where(cond)
            count_stmt = count_stmt.where(cond)

        total = int((await self.db.execute(count_stmt)).scalar() or 0)
        base = base.order_by(EmailMessage.sent_at.desc().nullslast()).offset(offset).limit(limit)
        items = list((await self.db.execute(base)).scalars().all())
        return items, total

    async def get_message(self, message_id: int) -> dict:
        message = await self._get(message_id)
        attachments = list(
            (
                await self.db.execute(
                    select(EmailAttachment)
                    .where(EmailAttachment.message_id == message_id)
                    .order_by(EmailAttachment.id)
                )
            )
            .scalars()
            .all()
        )
        return {"message": message, "attachments": attachments}

    async def _get(self, message_id: int) -> EmailMessage:
        message = (
            await self.db.execute(select(EmailMessage).where(EmailMessage.id == message_id))
        ).scalar_one_or_none()
        if not message:
            raise NotFoundError(f"Message {message_id} not found")
        return message

    async def set_flags(
        self, message_id: int, is_read: bool | None, is_starred: bool | None
    ) -> EmailMessage:
        """Apply the flag change to the DB only and return the message.

        The IMAP mirror is scheduled by the caller as a background task
        (:func:`push_flags_background`) so this stays fast — opening an IMAP
        connection per read/star toggle was the main cause of slow opens.
        """
        message = await self._get(message_id)
        if is_read is not None:
            message.is_read = is_read
        if is_starred is not None:
            message.is_starred = is_starred
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def _push_flags_to_imap_for(
        self, message_id: int, is_read: bool | None, is_starred: bool | None
    ) -> None:
        """Fetch the message then mirror flags to IMAP (used by background tasks)."""
        try:
            message = await self._get(message_id)
        except NotFoundError:
            return
        await self._push_flags_to_imap(message, is_read, is_starred)

    async def _push_flags_to_imap(
        self, message: EmailMessage, is_read: bool | None, is_starred: bool | None
    ) -> None:
        try:
            account = (
                await self.db.execute(
                    select(EmailAccount).where(EmailAccount.id == message.account_id)
                )
            ).scalar_one_or_none()
            folder = (
                await self.db.execute(
                    select(EmailFolder).where(EmailFolder.id == message.folder_id)
                )
            ).scalar_one_or_none()
            if not account or not folder:
                return
            password = security.decrypt(account.password_encrypted)
            async with ImapClient(
                account.imap_host,
                account.imap_port,
                account.imap_use_ssl,
                account.username,
                password,
            ) as imap:
                await imap.select(folder.folder_name)
                if is_read is not None:
                    op = "+FLAGS" if is_read else "-FLAGS"
                    await imap.uid_store(message.uid, op, "\\Seen")
                if is_starred is not None:
                    op = "+FLAGS" if is_starred else "-FLAGS"
                    await imap.uid_store(message.uid, op, "\\Flagged")
        except Exception:
            logger.debug("IMAP flag push failed for message %s", message.id, exc_info=True)

    async def delete_message(self, message_id: int) -> dict | None:
        """Delete the local copy immediately and return a move descriptor for
        the background server-side trash move (or ``None`` if none applicable).

        The IMAP round-trip used to run inline, which made deletes (and bulk
        deletes, which looped it) painfully slow. It now happens after the
        response via :func:`move_to_trash_background`.
        """
        message = await self._get(message_id)
        move = await self._describe_move(message)
        # Remove local copy (attachments cascade-delete; disk files orphaned — GC later).
        await self.db.delete(message)
        await self.db.commit()
        return move

    async def _describe_move(self, message: EmailMessage) -> dict | None:
        """Capture (account_id, source folder name, uid) for a background move."""
        folder = (
            await self.db.execute(select(EmailFolder).where(EmailFolder.id == message.folder_id))
        ).scalar_one_or_none()
        if not folder:
            return None
        return {
            "account_id": message.account_id,
            "moves": [(folder.folder_name, message.uid)],
        }

    async def bulk_delete(self, message_ids: list[int]) -> dict:
        """Local-delete many messages; return grouped move descriptors.

        Each message's server-side trash move is batched per account into one
        background task (see :func:`move_to_trash_background`).
        """
        by_account: dict[int, list[tuple[str, int]]] = {}
        for mid in message_ids:
            try:
                move = await self.delete_message(mid)
            except NotFoundError:
                continue
            except Exception:  # noqa: BLE001
                logger.debug("bulk_delete failed for message %s", mid, exc_info=True)
                continue
            if move:
                by_account.setdefault(move["account_id"], []).extend(move["moves"])
        return {"groups": by_account}

    async def mark_spam(self, message_id: int, is_spam: bool) -> EmailMessage:
        """User override of spam classification.

        Marking spam also adds the sender/domain to the blocklist (so future
        mail is auto-spam); marking not-spam clears the flag and removes any
        matching blocklist entry. ``spam_user_override`` pins the decision so a
        later rescore won't undo it.
        """
        message = await self._get(message_id)
        addr = (message.from_address or "").lower()
        domain = _domain_of(addr)
        spam_svc = SpamService(self.db)
        if is_spam:
            # Prefer a domain rule (broader), fall back to exact address.
            await spam_svc.add_rule(domain or addr, is_domain=bool(domain))
        else:
            await spam_svc.remove_rules_for(addr, domain)
        message.is_spam = is_spam
        message.spam_score = 1.0 if is_spam else 0.0
        message.spam_user_override = is_spam
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def block_sender(
        self, message_id: int, action: str = "junk", scope: str = "domain"
    ) -> dict:
        """Block the sender of ``message_id`` and apply ``action`` to every
        existing message from them in the same account.

        * ``action="junk"``  — flag them as spam (hidden from Inbox, shown in
          Spam) and best-effort IMAP-move them to the server Junk folder.
        * ``action="delete"``— delete the existing messages (local + background
          server trash-move). Future mail from the sender is skipped at sync.

        Returns ``{"rule": SpamBlocklist, "action": str, "affected": int}``.
        The caller schedules the background IMAP move using ``moves``.
        """
        message = await self._get(message_id)
        addr = (message.from_address or "").lower()
        domain = _domain_of(addr)
        use_domain = scope == "domain" and bool(domain)
        pattern = domain if use_domain else addr
        if not pattern:
            raise NotFoundError("Message has no sender address to block")

        spam_svc = SpamService(self.db)
        rule = await spam_svc.add_rule(pattern, is_domain=use_domain, action=action)

        # All existing messages from this sender/domain in the same account.
        match_cond = (
            (EmailMessage.from_address == addr)
            if not use_domain
            else (
                or_(
                    EmailMessage.from_address.like(f"%@{domain}"),
                    EmailMessage.from_address == domain,
                )
            )
        )
        targets = list(
            (
                await self.db.execute(
                    select(EmailMessage)
                    .where(
                        EmailMessage.account_id == message.account_id,
                        match_cond,
                    )
                    .order_by(EmailMessage.id)
                )
            )
            .scalars()
            .all()
        )

        moves: list[tuple[str, int]] = []
        affected_folders: set[int] = set()

        if action == "delete":
            for m in targets:
                desc = await self._describe_move(m)
                if desc:
                    moves.extend(desc["moves"])
                    affected_folders.add(m.folder_id)
                await self.db.delete(m)
        else:  # junk
            for m in targets:
                m.is_spam = True
                m.spam_score = 1.0
                m.spam_user_override = True
                desc = await self._describe_move(m)
                if desc:
                    moves.extend(desc["moves"])
                    affected_folders.add(m.folder_id)

        await self.db.commit()
        await self.db.refresh(rule)

        # Recount the folders we touched so badges stay accurate.
        touched_folders = (
            (await self.db.execute(select(EmailFolder).where(EmailFolder.id.in_(affected_folders))))
            .scalars()
            .all()
        )
        for folder in touched_folders:
            await EmailSyncService(self.db)._refresh_folder_counts(folder)

        return {
            "rule": rule,
            "action": action,
            "affected": len(targets),
            "account_id": message.account_id,
            "moves": moves,
        }

    async def attachment_path(self, message_id: int, attachment_id: int) -> Path:
        att = (
            await self.db.execute(
                select(EmailAttachment).where(
                    EmailAttachment.id == attachment_id,
                    EmailAttachment.message_id == message_id,
                )
            )
        ).scalar_one_or_none()
        if not att:
            raise NotFoundError(f"Attachment {attachment_id} not found")
        return Path(settings.MEDIA_DIR) / att.storage_path

    async def raw_path(self, message_id: int) -> Path:
        message = await self._get(message_id)
        if not message.raw_path:
            raise NotFoundError("Raw .eml not stored for this message")
        return Path(settings.MEDIA_DIR) / message.raw_path


# ── Compose service ────────────────────────────────────────────────────────


class EmailComposeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._reply_original: EmailMessage | None = None

    async def _load_reply_original(self, message_id: int | None) -> None:
        """Pre-fetch the message being replied to, for threading headers.

        ``_build_message`` is synchronous (it builds a MIME object), so the
        referenced message must be fetched eagerly before it runs.
        """
        if message_id is None:
            self._reply_original = None
            return
        self._reply_original = await EmailMessageService(self.db)._get(message_id)

    async def send(self, data: EmailCompose) -> dict[str, object]:
        account = await EmailAccountService(self.db).get(data.account_id)
        await self._load_reply_original(data.in_reply_to_message_id)
        msg = self._build_message(account, data)
        try:
            await send_via_smtp(
                account.smtp_host,
                account.smtp_port,
                account.smtp_use_tls,
                account.username,
                security.decrypt(account.password_encrypted),
                msg,
            )
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "sent_message_id": None, "error": _exc_message(exc)}

        # Append to the Sent folder on the server so future syncs capture it.
        raw = msg.as_bytes()
        await self._append_to_special(account, "sent", "\\Seen", raw)
        self._cleanup_temp_attachments(data.attachment_ids)
        return {"success": True, "sent_message_id": None, "error": None}

    async def save_draft(self, data: EmailCompose) -> dict[str, object]:
        account = await EmailAccountService(self.db).get(data.account_id)
        await self._load_reply_original(data.in_reply_to_message_id)
        msg = self._build_message(account, data, as_draft=True)
        raw = msg.as_bytes()
        await self._append_to_special(account, "drafts", "\\Draft", raw)
        self._cleanup_temp_attachments(data.attachment_ids)
        return {"success": True, "sent_message_id": None, "error": None}

    def _build_message(self, account: EmailAccount, data: EmailCompose, as_draft: bool = False):
        from email.message import EmailMessage as MimeMessage
        from email.utils import formatdate, make_msgid

        msg = MimeMessage()
        msg["From"] = (
            f"{account.display_name} <{account.email_address}>"
            if account.display_name
            else account.email_address
        )
        msg["To"] = ", ".join(data.to)
        if data.cc:
            msg["Cc"] = ", ".join(data.cc)
        msg["Subject"] = data.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=account.email_address.split("@")[-1])

        # Reply threading (original pre-fetched in send()/save_draft()).
        original = self._reply_original
        if data.in_reply_to_message_id and original is not None:
            msg["In-Reply-To"] = original.message_id or ""
            if original.references:
                msg["References"] = f"{original.references} {original.message_id or ''}".strip()
            elif original.message_id:
                msg["References"] = original.message_id

        msg.set_content(data.text_body or "")
        if data.html_body:
            msg.add_alternative(data.html_body, subtype="html")

        for temp_id in data.attachment_ids:
            meta = _TEMP_ATTACHMENTS.get(temp_id)
            if not meta:
                continue
            payload = meta["path"].read_bytes()
            maintype, _, subtype = meta["content_type"].partition("/")
            msg.add_attachment(
                payload,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=meta["filename"],
            )
        return msg

    async def _append_to_special(
        self, account: EmailAccount, special: str, flag: str, raw: bytes
    ) -> None:
        try:
            folder = (
                (
                    await self.db.execute(
                        select(EmailFolder).where(
                            EmailFolder.account_id == account.id,
                            EmailFolder.special_use == special,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if not folder:
                return
            password = security.decrypt(account.password_encrypted)
            async with ImapClient(
                account.imap_host,
                account.imap_port,
                account.imap_use_ssl,
                account.username,
                password,
            ) as imap:
                await imap.append(folder.folder_name, flag, raw)
                # Re-sync that folder so the appended message lands in our DB.
                await EmailSyncService(self.db).sync_folder(imap, account, folder)
        except Exception:
            logger.debug("APPEND to %s failed", special, exc_info=True)

    @staticmethod
    def _cleanup_temp_attachments(ids: list[int]) -> None:
        # ids here are temp string ids carried in EmailCompose.attachment_ids
        for temp_id in ids:
            meta = _TEMP_ATTACHMENTS.pop(str(temp_id), None)
            if meta:
                meta["path"].unlink(missing_ok=True)


# ── Temp attachment upload ─────────────────────────────────────────────────


def store_temp_attachment(filename: str, content_type: str, payload: bytes) -> dict:
    temp_dir = Path(settings.MEDIA_DIR) / "email" / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_id = secrets.token_urlsafe(12)
    path = temp_dir / f"{temp_id}_{_sanitize(filename)}"
    path.write_bytes(payload)
    _TEMP_ATTACHMENTS[temp_id] = {
        "path": path,
        "filename": filename,
        "content_type": content_type,
        "size": len(payload),
    }
    return {"id": temp_id, "filename": filename, "file_size": len(payload)}
