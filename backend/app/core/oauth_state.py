"""CSRF state-token store for OAuth loopback flows.

Each cloud-backup provider (Google Drive, Dropbox, OneDrive, Box) runs an OAuth
loopback flow: the browser is sent to the provider's consent screen carrying a
single-use ``state`` token, which the provider echoes back to ``/callback``.
``OAuthStateStore`` issues and single-use-consumes those tokens with a TTL, so a
forged or stale redirect cannot be replayed.

Each provider keeps its own instance, so a state issued by one provider's
``/auth-url`` cannot be consumed by another provider's ``/callback``.
"""

from __future__ import annotations

import secrets
import time

# State tokens are valid for 10 minutes — plenty for a human to complete consent.
DEFAULT_TTL_SECONDS = 600


class OAuthStateStore:
    """In-memory, single-use CSRF state tokens with a TTL."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._pending: dict[str, float] = {}

    def issue(self) -> str:
        """Drop expired entries and return a fresh single-use state token."""
        now = time.time()
        for key in [k for k, created in self._pending.items() if now - created > self._ttl]:
            self._pending.pop(key, None)
        state = secrets.token_urlsafe(24)
        self._pending[state] = now
        return state

    def consume(self, state: str | None) -> bool:
        """Single-use consume: True only if ``state`` exists and is not expired."""
        if not state:
            return False
        created = self._pending.pop(state, None)
        return created is not None and (time.time() - created) <= self._ttl
