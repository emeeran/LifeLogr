"""CSRF state-token store for OAuth loopback flows.

Each cloud-backup provider (Google Drive, Dropbox, OneDrive, Box) runs an OAuth
loopback flow: the browser is sent to the provider's consent screen carrying a
single-use ``state`` token, which the provider echoes back to ``/callback``.
``OAuthStateStore`` issues and single-use-consumes those tokens with a TTL, so a
forged or stale redirect cannot be replayed.

``state`` alone only proves *our* callback issued the flow; it does not bind the
authorization code to the client that started it. Every provider here therefore
also runs PKCE (RFC 7636): a random ``code_verifier`` is kept server-side while
its SHA-256 ``code_challenge`` travels in the consent URL, and the verifier is
required again at the token exchange. A stolen authorization code (it transits
the browser's address bar and the provider's redirect) is useless without the
verifier that never left the backend.

Each provider keeps its own instance, so a state issued by one provider's
``/auth-url`` cannot be consumed by another provider's ``/callback``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time

# State tokens are valid for 10 minutes — plenty for a human to complete consent.
DEFAULT_TTL_SECONDS = 600

# RFC 7636 §4.1: the verifier is 43-128 characters from the unreserved set.
_VERIFIER_BYTES = 64  # token_urlsafe(64) → 86 unreserved characters


def generate_code_verifier() -> str:
    """Return a fresh PKCE code_verifier (86 urlsafe characters, RFC-compliant)."""
    return secrets.token_urlsafe(_VERIFIER_BYTES)


def code_challenge_s256(verifier: str) -> str:
    """Derive the S256 ``code_challenge`` for *verifier* (base64url, no padding)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class OAuthStateStore:
    """In-memory, single-use CSRF state tokens with a TTL (and optional PKCE)."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._pending: dict[str, float] = {}
        self._verifiers: dict[str, str] = {}

    def issue(self) -> str:
        """Drop expired entries and return a fresh single-use state token."""
        now = time.time()
        for key in [k for k, created in self._pending.items() if now - created > self._ttl]:
            self._pending.pop(key, None)
            self._verifiers.pop(key, None)
        state = secrets.token_urlsafe(24)
        self._pending[state] = now
        return state

    def issue_with_pkce(self) -> tuple[str, str, str]:
        """Issue a state token bound to a PKCE pair.

        Returns ``(state, code_verifier, code_challenge)``. The verifier stays
        in memory until :meth:`take` hands it to the token exchange — it is
        never sent to the browser.
        """
        state = self.issue()
        verifier = generate_code_verifier()
        self._verifiers[state] = verifier
        return state, verifier, code_challenge_s256(verifier)

    def consume(self, state: str | None) -> bool:
        """Single-use consume: True only if ``state`` exists and is not expired."""
        if not state:
            return False
        created = self._pending.pop(state, None)
        self._verifiers.pop(state, None)
        return created is not None and (time.time() - created) <= self._ttl

    def take(self, state: str | None) -> str | None:
        """Consume a PKCE-bound state and return its verifier, or ``None``.

        The single-use + TTL rules are the same as :meth:`consume`; the returned
        verifier is the one to put in the token-exchange request. ``None`` means
        the state was unknown, expired, or never carried a verifier — in every
        case the callback must refuse to exchange the code.
        """
        if not state:
            return None
        created = self._pending.pop(state, None)
        verifier = self._verifiers.pop(state, None)
        if created is None or (time.time() - created) > self._ttl:
            return None
        return verifier
