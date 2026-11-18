"""OAuthStateStore — CSRF state-token issue/consume lifecycle.

These lock the single-use + TTL contract that every OAuth loopback callback
(Google Drive / Dropbox / OneDrive / Box) relies on. A regression here is an
account-takeover vector (a forged/stale redirect would be accepted), so the
cases below are the security boundary.
"""

from __future__ import annotations

import time

from app.core.oauth_state import OAuthStateStore


def test_issue_returns_nonempty_token() -> None:
    state = OAuthStateStore().issue()
    assert isinstance(state, str)
    assert len(state) >= 16  # token_urlsafe(24) → ~32 chars


def test_consume_valid_then_single_use() -> None:
    store = OAuthStateStore()
    state = store.issue()
    assert store.consume(state) is True
    # Single-use: a second consume of the same token must fail.
    assert store.consume(state) is False


def test_consume_rejects_empty_and_unknown() -> None:
    store = OAuthStateStore()
    store.issue()
    assert store.consume(None) is False
    assert store.consume("") is False
    assert store.consume("not-a-real-state") is False


def test_expired_state_is_rejected() -> None:
    store = OAuthStateStore(ttl_seconds=60)
    state = store.issue()
    # Force the issued timestamp beyond the TTL without waiting.
    store._pending[state] = time.time() - 120
    assert store.consume(state) is False


def test_issue_sweeps_expired_entries() -> None:
    store = OAuthStateStore(ttl_seconds=60)
    old = store.issue()
    store._pending[old] = time.time() - 120
    new = store.issue()
    assert new != old
    assert old not in store._pending


def test_stores_are_isolated_per_provider() -> None:
    store_a = OAuthStateStore()
    store_b = OAuthStateStore()
    state = store_a.issue()
    # A state issued by provider A must not be consumable by provider B's store.
    assert store_b.consume(state) is False
    assert store_a.consume(state) is True
