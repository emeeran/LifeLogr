"""Unit tests for the low-level IMAP/SMTP helpers in ``email_protocol``.

These don't talk to a real server — a fake imaplib object records what the
``ImapClient`` hands it, so we can assert command arguments directly. The core
regression: mailbox names with spaces must be quoted, because Python 3.11's
``imaplib._command`` does no quoting of its own.
"""

import pytest

from app.services.email_protocol import ImapClient, _quote_mailbox, parse_message


class _FakeImap:
    """Minimal stand-in for imaplib.IMAP4 recording the mailbox it selects."""

    def __init__(self) -> None:
        self.selected: str | None = None
        self.appended: tuple | None = None
        self.moved: tuple | None = None
        self.untagged_responses = {"UIDVALIDITY": [b"12345"]}

    def select(self, mailbox: str) -> tuple[str, list[bytes]]:
        self.selected = mailbox
        return ("OK", [b"7"])

    def append(self, mailbox: str, flags: str, date, raw: bytes) -> tuple[str, list]:
        self.appended = (mailbox, flags, date, raw)
        return ("OK", [b"APPEND"])

    def uid(self, command: str, *args):
        self.moved = (command, *args)
        return ("OK", [b"MOVE done"])


def _client() -> ImapClient:
    c = ImapClient("host", 993, True, "user", "pw")
    c._imap = _FakeImap()
    return c


@pytest.mark.parametrize(
    "name, expected",
    [
        ("INBOX", "INBOX"),  # bare atom → unchanged
        ("Sent", "Sent"),
        ("[Gmail]/All Mail", '"[Gmail]/All Mail"'),  # space → quoted
        ("[Gmail]/Sent Mail", '"[Gmail]/Sent Mail"'),
        ("Sync Issues", '"Sync Issues"'),
        ("Sync Issues/Server Failures", '"Sync Issues/Server Failures"'),
        ("[Gmail]", '"[Gmail]"'),  # brackets aren't atoms → quoted
        ("[Gmail]/Spam", '"[Gmail]/Spam"'),
        ('a"b', '"a\\"b"'),  # embedded quote escaped
        ("", '""'),  # empty → quoted
    ],
)
def test_quote_mailbox(name: str, expected: str) -> None:
    assert _quote_mailbox(name) == expected


async def test_select_quotes_spacey_folder():
    """The regression: ``[Gmail]/All Mail`` must reach imaplib already quoted."""
    c = _client()
    count, uidvalidity = await c.select("[Gmail]/All Mail")
    assert count == 7
    assert uidvalidity == 12345
    assert c.imap.selected == '"[Gmail]/All Mail"'


async def test_select_leaves_atom_unquoted():
    c = _client()
    await c.select("INBOX")
    assert c.imap.selected == "INBOX"


async def test_append_quotes_destination():
    c = _client()
    await c.append("[Gmail]/Drafts", "\\Drafts", b"raw")
    assert c.imap.appended[0] == '"[Gmail]/Drafts"'


async def test_uid_move_quotes_destination():
    c = _client()
    await c.uid_move(42, "[Gmail]/Trash")
    assert c.imap.moved == ("MOVE", "42", '"[Gmail]/Trash"')


def test_parse_message_malformed_from_does_not_crash():
    """A ``From`` with no '@' (e.g. Mailer-Daemon) must not abort parsing.

    normalize_email rejects such addresses; previously that exception propagated
    out of parse_message → _store_message, wedging the folder sync on that UID.
    Now it falls back to the raw value.
    """
    raw = (
        b"From: Mailer-Daemon\r\n"
        b"To: owner@example.com\r\n"
        b"Subject: Delivery failed\r\n"
        b"Message-ID: <bounced@host>\r\n"
        b"\r\n"
        b"Undeliverable.\r\n"
    )
    msg = parse_message(raw)
    assert msg.from_address == "Mailer-Daemon"  # raw fallback, no crash
    assert msg.subject == "Delivery failed"
