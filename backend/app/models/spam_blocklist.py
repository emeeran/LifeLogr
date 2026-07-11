"""SpamBlocklist ORM model — user-blocked senders / domains.

A message whose ``from_address`` (exact) or its domain matches a blocklist row
is classified as spam during sync / on the next rescore. Paired with the
contact allowlist (saved contacts are never spam) and the heuristic scorer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SpamBlocklist(Base):
    __tablename__ = "spam_blocklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    # For a domain rule this is the bare domain (e.g. "spam.example.com"); for a
    # sender rule it is the full address (e.g. "nobody@spam.example.com").
    pattern: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_domain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
