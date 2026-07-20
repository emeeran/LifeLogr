"""Unit tests for email_protocol.parse_message edge cases."""

from app.services.email_protocol import parse_message


def _msg(from_header: str) -> bytes:
    return (
        b"From: " + from_header.encode() + b"\r\n"
        b"To: friend@example.com\r\n"
        b"Subject: Hello\r\n"
        b"Date: Thu, 17 Jul 2026 12:00:00 +0000\r\n"
        b"\r\n"
        b"Body.\r\n"
    )


def test_parse_message_valid_from_normalizes():
    p = parse_message(_msg("Alice <alice@example.com>"))
    assert p.from_address == "alice@example.com"
    assert p.from_name == "Alice"


def test_parse_message_malformed_from_does_not_raise():
    # System/bounce senders (e.g. Mailer-Daemon) carry a From with no @-sign.
    # This used to abort the entire folder sync via normalize_email raising
    # ValueError; it must now fall back to the raw value so the message is
    # still stored and the sync continues.
    p = parse_message(_msg("Mailer-Daemon"))
    assert p.from_address == "Mailer-Daemon"
    assert p.from_name is None
