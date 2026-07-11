"""SpamService — offline heuristic spam filter with allowlist + blocklist.

The scorer is a pure function (easy to unit test); ``SpamService.classify``
wraps it with two override layers:
  1. **Blocklist** — a sender address or domain the user blocked → always spam.
  2. **Contact allowlist** — mail from a saved contact → never spam.
Otherwise the heuristic ``score_message`` decides at ``SPAM_THRESHOLD``.

Messages store the effective ``is_spam`` flag plus ``spam_user_override`` so a
later rescore never overrides an explicit user decision.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.email_message import EmailMessage
from app.models.spam_blocklist import SpamBlocklist
from app.services.email_protocol import ParsedMessage

logger = logging.getLogger(__name__)

SPAM_THRESHOLD = 0.5

# TLDs disproportionately used by spam. Weighted heavily.
_SUSPICIOUS_TLDS = {
    ".xyz", ".click", ".top", ".work", ".bid", ".loan", ".date", ".stream",
    ".gq", ".tk", ".ml", ".cf", ".ga", ".kim", ".science", ".review",
    ".racing", ".accountant", ".cricket", ".party", ".download", ".men",
    ".pw", ".icu", ".cam", ".sbs", ".cyou", ".monster", ".bond", ".country",
    ".rest", ".vip", ".fit", ".win",
}

_SPAMMY_WORDS_SUBJECT = {
    "winner", "you've won", "you have won", "congratulations", "lottery",
    "free", "guarantee", "guaranteed", "viagra", "cialis", "casino",
    "crypto", "bitcoin", "make money", "earn money", "work from home",
    "weight loss", "miracle", "risk-free", "100% free", "act now",
    "limited time", "dear winner", "claim your", "claim now", "prize",
    "selected to win", "no prescription", "cheap meds",
}

_SPAMMY_WORDS_BODY = {
    "click here", "buy now", "order now", "best price", "lowest price",
    "100% guaranteed", "no prescription", "viagra", "cialis", "weight loss",
    "make money", "earn extra", "work from home", "this is not spam",
    "money-back guarantee", "risk-free trial", "exclusive deal",
    "double your income", "instant approval",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def _body_text(text: str | None, html: str | None) -> str:
    if text:
        return text.lower()
    if html:
        return _TAG_RE.sub(" ", html).lower()
    return ""


def _caps_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def score_message(
    subject: str | None,
    from_address: str,
    from_name: str | None,
    text: str | None,
    html: str | None,
) -> float:
    """Heuristic spam score in [0, 1]. Pure function — no DB, no IO."""
    score = 0.0
    subj = (subject or "").strip()
    subj_l = subj.lower()
    domain = _domain_of(from_address.lower())
    body = _body_text(text, html)

    # Sender domain reputation — strongest single signal.
    if domain and any(domain.endswith(t) for t in _SUSPICIOUS_TLDS):
        score += 0.35

    if not subj_l:
        score += 0.15  # missing subject
    else:
        if len([c for c in subj if c.isalpha()]) >= 5 and _caps_ratio(subj) > 0.8:
            score += 0.2  # ALL CAPS shouting
        if any(w in subj_l for w in _SPAMMY_WORDS_SUBJECT):
            score += 0.35
        if subj.count("!") >= 3 or "!!!" in subj:
            score += 0.1

    # Display-name / address mismatch (e.g. name "PayPal" from a random domain).
    fn = (from_name or "").lower()
    if domain and fn and ("http" in fn or ("@" in fn and not fn.endswith(domain))):
        score += 0.1

    if body:
        link_count = body.count("http")
        words = body.split()
        if link_count >= 5 or (words and link_count / max(len(words), 1) > 0.05):
            score += 0.2  # link-heavy
        if _caps_ratio(body) > 0.35:
            score += 0.15
        if any(w in body for w in _SPAMMY_WORDS_BODY):
            score += 0.2

    return min(score, 1.0)


class SpamService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def classify(self, parsed: ParsedMessage) -> tuple[float, bool]:
        """Return ``(score, is_spam)`` for a parsed message, honouring overrides."""
        addr = (parsed.from_address or "").lower()
        domain = _domain_of(addr)
        if await self.is_blocked(addr, domain):
            return 1.0, True
        if await self.is_contact(addr):
            return 0.0, False
        score = score_message(
            parsed.subject, addr, parsed.from_name, parsed.text_body, parsed.html_body
        )
        return score, score >= SPAM_THRESHOLD

    # ── override layers ───────────────────────────────────────────────────

    @staticmethod
    def _blocklist_conditions(addr: str, domain: str) -> list:
        """OR-conditions matching a sender by exact address and/or domain."""
        conditions = []
        if addr:
            conditions.append(SpamBlocklist.pattern == addr)
        if domain:
            conditions.append(
                (SpamBlocklist.is_domain.is_(True)) & (SpamBlocklist.pattern == domain)
            )
        return conditions

    async def is_blocked(self, addr: str, domain: str) -> bool:
        conditions = self._blocklist_conditions(addr, domain)
        if not conditions:
            return False
        found = (
            await self.db.execute(select(SpamBlocklist.id).where(or_(*conditions)))
        ).scalar_one_or_none()
        return found is not None

    async def is_contact(self, addr: str) -> bool:
        if not addr or "@" not in addr:
            return False
        like = f"%{addr}%"
        found = (
            await self.db.execute(
                select(Contact.id).where(
                    or_(Contact.email == addr, Contact.emails_extra.like(like))
                )
            )
        ).scalar_one_or_none()
        return found is not None

    # ── blocklist CRUD ────────────────────────────────────────────────────

    async def list_rules(self) -> list[SpamBlocklist]:
        return list(
            (
                await self.db.execute(
                    select(SpamBlocklist).order_by(SpamBlocklist.created_at.desc())
                )
            ).scalars().all()
        )

    async def add_rule(
        self, pattern: str, is_domain: bool, action: str = "junk"
    ) -> SpamBlocklist:
        pattern = pattern.strip().lower()
        action = action if action in ("junk", "delete") else "junk"
        # De-dupe. If the same pattern/is_domain exists, adopt the new action.
        existing = (
            await self.db.execute(
                select(SpamBlocklist).where(
                    (SpamBlocklist.pattern == pattern)
                    & (SpamBlocklist.is_domain.is_(is_domain))
                )
            )
        ).scalar_one_or_none()
        if existing:
            if existing.action != action:
                existing.action = action
                await self.db.commit()
                await self.db.refresh(existing)
            return existing
        rule = SpamBlocklist(pattern=pattern, is_domain=is_domain, action=action)
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def block_action(self, addr: str, domain: str) -> str | None:
        """Return the configured action ('junk'|'delete') if the sender is
        blocked, else ``None``."""
        conditions = self._blocklist_conditions(addr, domain)
        if not conditions:
            return None
        row = (
            await self.db.execute(select(SpamBlocklist).where(or_(*conditions)))
        ).scalar_one_or_none()
        return row.action if row else None

    async def remove_rule(self, rule_id: int) -> None:
        rule = (
            await self.db.execute(select(SpamBlocklist).where(SpamBlocklist.id == rule_id))
        ).scalar_one_or_none()
        if rule:
            await self.db.delete(rule)
            await self.db.commit()

    async def remove_rules_for(self, addr: str, domain: str) -> None:
        """Drop blocklist entries matching a sender (used by 'mark not spam')."""
        conditions = self._blocklist_conditions(addr, domain)
        if not conditions:
            return
        rows = list(
            (
                await self.db.execute(select(SpamBlocklist).where(or_(*conditions)))
            ).scalars().all()
        )
        for r in rows:
            await self.db.delete(r)
        if rows:
            await self.db.commit()

    # ── rescore existing messages (respects user overrides) ───────────────

    async def rescore(self, account_id: int | None = None) -> int:
        """Recompute heuristic scores for messages without a user override."""
        stmt = select(EmailMessage).where(EmailMessage.spam_user_override.is_(None))
        if account_id is not None:
            stmt = stmt.where(EmailMessage.account_id == account_id)
        msgs = list((await self.db.execute(stmt)).scalars().all())
        changed = 0
        for m in msgs:
            addr = (m.from_address or "").lower()
            domain = _domain_of(addr)
            if await self.is_blocked(addr, domain):
                m.is_spam, m.spam_score = True, 1.0
            elif await self.is_contact(addr):
                m.is_spam, m.spam_score = False, 0.0
            else:
                score = score_message(m.subject, addr, m.from_name, m.text_body, m.html_body)
                m.is_spam, m.spam_score = score >= SPAM_THRESHOLD, score
            changed += 1
        await self.db.commit()
        return changed
