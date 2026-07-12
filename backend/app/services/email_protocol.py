"""Low-level email protocol helpers.

Async-friendly IMAP via stdlib ``imaplib`` wrapped in ``asyncio.to_thread``
(imaplib's ``(type, data)`` FETCH responses are reliably parseable), and
``aiosmtplib`` for SMTP. Everything behind one module so the IMAP transport
could be swapped for a native-async client later without touching the service
layer.

MIME parsing uses the stdlib ``email`` package with the modern ``default``
policy (``get_body()`` / ``iter_attachments()``).
"""

from __future__ import annotations

import asyncio
import email.utils
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message

import aiosmtplib
from email_validator import EmailNotValidError, validate_email

logger = logging.getLogger(__name__)


# ── Address / snippet helpers ──────────────────────────────────────────────


def normalize_email(addr: str) -> str:
    """Lowercase + validate an address; raises ValueError if invalid."""
    try:
        info = validate_email(addr, check_deliverability=False)
        return info.normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email address {addr!r}: {exc}") from exc


def decode_addresses(header_values: list[str]) -> list[dict]:
    """Parse RFC 5322 address headers into ``[{"name": str|None, "address": str}]``."""
    out: list[dict] = []
    for name, addr in email.utils.getaddresses(header_values):
        if not addr:
            continue
        try:
            out.append({"name": name or None, "address": normalize_email(addr)})
        except ValueError:
            continue  # skip unparseable addresses
    return out


_TAG_RE = re.compile(r"<[^>]+>")


def make_snippet(text: str | None, html: str | None, length: int = 300) -> str | None:
    """Best-effort single-line preview of a message body."""
    if text:
        source = text
    elif html:
        source = _TAG_RE.sub(" ", html)
    else:
        return None
    snippet = " ".join(source.split())
    return snippet[:length] + ("…" if len(snippet) > length else "")


# ── Parsed message ─────────────────────────────────────────────────────────


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    payload: bytes
    content_id: str | None
    is_inline: bool


@dataclass
class ParsedMessage:
    message_id: str | None
    subject: str | None
    from_name: str | None
    from_address: str | None
    to_addresses: list[dict] = field(default_factory=list)
    cc_addresses: list[dict] = field(default_factory=list)
    bcc_addresses: list[dict] = field(default_factory=list)
    reply_to: str | None = None
    sent_at: datetime | None = None
    in_reply_to: str | None = None
    references: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    snippet: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)


def parse_message(raw: bytes) -> ParsedMessage:
    """Parse raw RFC822 bytes into a :class:`ParsedMessage`."""
    from email import policy
    from email.parser import BytesParser

    msg: Message = BytesParser(policy=policy.default).parsebytes(raw)

    def _header(name: str) -> str | None:
        val = msg.get(name)
        return str(val).strip() if val else None

    subject = _header("Subject")
    msg_id = _header("Message-ID")
    in_reply_to = _header("In-Reply-To")
    references = _header("References")
    reply_to_raw = _header("Reply-To")

    from_name, from_addr = email.utils.parseaddr(_header("From") or "")
    to_addrs = decode_addresses(msg.get_all("To", []))
    cc_addrs = decode_addresses(msg.get_all("Cc", []))
    bcc_addrs = decode_addresses(msg.get_all("Bcc", []))

    sent_at = None
    date_raw = _header("Date")
    if date_raw:
        try:
            dt = email.utils.parsedate_to_datetime(date_raw)
            sent_at = dt.replace(tzinfo=None) if dt else None
        except (TypeError, ValueError):
            sent_at = None

    # Bodies
    text_body = html_body = None
    try:
        body = msg.get_body(preferencelist=("plain",))
        if body is not None:
            text_body = body.get_content()
    except Exception:
        text_body = None
    try:
        body = msg.get_body(preferencelist=("html",))
        if body is not None:
            html_body = body.get_content()
    except Exception:
        html_body = None

    # Attachments
    attachments: list[ParsedAttachment] = []
    try:
        for part in msg.iter_attachments():
            cid = part.get("Content-ID")
            cid = cid.strip("<> ") if cid else None
            disposition = str(part.get("Content-Disposition", "")).lower()
            is_inline = "inline" in disposition or cid is not None
            filename = part.get_filename() or "attachment"
            try:
                payload = part.get_payload(decode=True) or b""
                if not payload and part.get_content_type().startswith("text/"):
                    payload = part.get_content().encode("utf-8", "replace")
            except Exception:
                payload = b""
            attachments.append(
                ParsedAttachment(
                    filename=filename,
                    content_type=part.get_content_type(),
                    payload=payload,
                    content_id=cid,
                    is_inline=is_inline,
                )
            )
    except Exception:
        logger.debug("Attachment extraction partial failure", exc_info=True)

    reply_to_addr = None
    if reply_to_raw:
        _, a = email.utils.parseaddr(reply_to_raw)
        if a:
            try:
                reply_to_addr = normalize_email(a)
            except ValueError:
                reply_to_addr = a

    return ParsedMessage(
        message_id=msg_id,
        subject=subject,
        from_name=from_name or None,
        from_address=normalize_email(from_addr) if from_addr else None,
        to_addresses=to_addrs,
        cc_addresses=cc_addrs,
        bcc_addresses=bcc_addrs,
        reply_to=reply_to_addr,
        sent_at=sent_at,
        in_reply_to=in_reply_to,
        references=references,
        text_body=text_body,
        html_body=html_body,
        snippet=make_snippet(text_body, html_body),
        attachments=attachments,
    )


# ── IMAP client (imaplib in a thread) ──────────────────────────────────────


class ImapClient:
    """Async wrapper around blocking ``imaplib``, each call run in a thread."""

    def __init__(self, host: str, port: int, use_ssl: bool, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.username = username
        self.password = password
        self._imap: imaplib.IMAP4 | None = None

    async def __aenter__(self) -> ImapClient:
        cls = imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
        self._imap = await asyncio.to_thread(cls, self.host, self.port)
        assert self._imap is not None
        await asyncio.to_thread(self._imap.login, self.username, self.password)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._imap is not None:
            try:
                await asyncio.to_thread(self._imap.logout)
            except Exception:
                pass
            self._imap = None

    @property
    def imap(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise RuntimeError("ImapClient used outside 'async with'")
        return self._imap

    async def list_folders(self) -> list[tuple[str, str]]:
        """Return ``(folder_name, raw_flags)`` tuples."""
        typ, data = await asyncio.to_thread(self.imap.list, '""', "*")
        folders: list[tuple[str, str]] = []
        if typ != "OK":
            return folders
        for item in data:
            if not item:
                continue
            line = item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item)
            # Form: (\HasNoChildren) "/" "INBOX"  or  (\HasChildren) "." INBOX
            m = re.match(r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)$', line)
            if not m:
                continue
            name = m.group("name").strip().strip('"')
            folders.append((name, m.group("flags")))
        return folders

    async def select(self, folder: str) -> tuple[int, int | None]:
        """Select a folder, returning (message_count, uidvalidity)."""
        typ, data = await asyncio.to_thread(self.imap.select, folder)
        if typ != "OK":
            raise RuntimeError(f"IMAP SELECT {folder!r} failed: {data}")
        count = 0
        if data and data[0]:
            try:
                count = int(data[0])
            except (TypeError, ValueError):
                count = 0
        uidvalidity = self.imap.untagged_responses.get("UIDVALIDITY", [b"0"])[0]
        try:
            uidvalidity = int(uidvalidity)
        except (TypeError, ValueError):
            uidvalidity = None
        return count, uidvalidity

    async def uid_search(self, criteria: str) -> list[int]:
        typ, data = await asyncio.to_thread(self.imap.uid, "SEARCH", None, criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        return [int(x) for x in data[0].split()]

    async def uid_fetch_rfc822(self, uid: int) -> tuple[bytes | None, list[str]]:
        """Fetch raw RFC822 bytes + parsed flags for one UID."""
        typ, data = await asyncio.to_thread(self.imap.uid, "FETCH", str(uid), "(RFC822 FLAGS)")
        if typ != "OK" or not data:
            return None, []
        raw: bytes | None = None
        flags: list[str] = []
        for item in data:
            if isinstance(item, tuple):
                header = (
                    item[0].decode("utf-8", "replace")
                    if isinstance(item[0], bytes)
                    else str(item[0])
                )
                if isinstance(item[1], bytes):
                    raw = item[1]
                m = re.search(r"FLAGS \(([^)]*)\)", header)
                if m:
                    flags = m.group(1).split()
            elif isinstance(item, bytes):
                # trailing b')' or the literal if single-part
                text = item.decode("utf-8", "replace")
                if "FLAGS" in text:
                    m2 = re.search(r"FLAGS \(([^)]*)\)", text)
                    if m2:
                        flags = m2.group(1).split()
        return raw, flags

    async def uid_store(self, uid: int, op: str, flag: str) -> None:
        await asyncio.to_thread(self.imap.uid, "STORE", str(uid), op, f"({flag})")

    async def append(self, folder: str, flags: str, raw: bytes) -> None:
        await asyncio.to_thread(self.imap.append, folder, flags, None, raw)

    async def uid_move(self, uid: int, dest_folder: str) -> bool:
        """Move a message; returns False if the server lacks MOVE."""
        try:
            typ, _ = await asyncio.to_thread(self.imap.uid, "MOVE", str(uid), dest_folder)
            return typ == "OK"
        except imaplib.IMAP4.error:
            return False


# ── SMTP ───────────────────────────────────────────────────────────────────


async def send_via_smtp(
    host: str, port: int, use_tls: bool, username: str, password: str, message: Message
) -> None:
    """Connect, login, and send a single message (raises on failure)."""
    smtp = aiosmtplib.SMTP(hostname=host, port=port, use_tls=use_tls, timeout=30)
    await smtp.connect()
    if not use_tls:
        # Opportunistic STARTTLS on submission port 587. If a MITM strips
        # STARTTLS the credentials would otherwise go in the clear — log loudly
        # so it's visible (we still proceed; many providers fall back to cleartext).
        try:
            await smtp.starttls()
        except Exception:
            logger.warning(
                "STARTTLS negotiation with %s failed; continuing without TLS",
                host,
                exc_info=True,
            )
    await smtp.login(username, password)
    try:
        await smtp.send_message(message)
    finally:
        try:
            await smtp.quit()
        except Exception:
            pass
