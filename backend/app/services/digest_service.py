"""DigestService — weekly AI-generated journal summaries."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.digest import Digest
from app.models.entry import Entry
from app.models.sentiment import EntrySentiment
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def generate_for_week(self, week_start: date) -> Digest:
        """Generate a weekly digest using map-reduce summarization."""
        week_end = week_start + timedelta(days=6)

        # Load entries for the week
        result = await self.db.execute(
            select(Entry)
            .where(
                ~Entry.is_deleted,
                Entry.entry_date >= week_start,
                Entry.entry_date <= week_end,
            )
            .order_by(Entry.entry_date)
        )
        entries = list(result.scalars().all())

        if not entries:
            raise ValueError(f"No entries found for week {week_start} to {week_end}")

        # Map: gather summaries and sentiments
        entry_summaries = []
        sentiments = []

        for entry in entries:
            summary = entry.summary or entry.body[:200]
            entry_summaries.append(f"[{entry.entry_date}] {entry.title or 'Untitled'}: {summary}")

        # Load sentiments for these entries
        entry_ids = [e.id for e in entries]
        sent_result = await self.db.execute(
            select(EntrySentiment).where(EntrySentiment.entry_id.in_(entry_ids))
        )
        for sent in sent_result.scalars().all():
            sentiments.append(
                f"{sent.primary_emotion} (intensity: {sent.intensity}, valence: {sent.valence:.1f})"
            )

        # Reduce: send to LLM
        ollama = OllamaService()
        prompt = (
            "You are a thoughtful journal companion. Review this week's journal entries and write a warm, insightful weekly summary.\n"
            "Return ONLY a JSON object with this structure:\n"
            '{"themes": ["theme1", "theme2", ...], "emotional_trajectory": "description of how emotions changed through the week", '
            '"notable_moments": ["moment1", "moment2", ...], "summary_text": "A warm, 3-5 sentence summary of the week"}\n\n'
            "Entries:\n" + "\n".join(entry_summaries[:20]) + "\n\n"
            f"Detected emotions: {', '.join(sentiments[:20]) if sentiments else 'none'}"
        )

        raw = await ollama._generate(prompt, temperature=0.6)
        parsed = ollama._parse_json_response(raw)
        analysis = parsed if isinstance(parsed, dict) else None

        themes = json.dumps(analysis.get("themes", [])) if analysis else "[]"
        trajectory = (
            analysis.get("emotional_trajectory", "No trajectory data") if analysis else "No data"
        )
        moments = json.dumps(analysis.get("notable_moments", [])) if analysis else "[]"
        summary_text = (
            analysis.get("summary_text", "Weekly digest generated.") if analysis else "Digest"
        )

        # Delete existing digest for this week if any
        existing = await self.db.execute(select(Digest).where(Digest.week_start == week_start))
        old = existing.scalar_one_or_none()
        if old:
            await self.db.delete(old)

        digest = Digest(
            week_start=week_start,
            week_end=week_end,
            themes=themes,
            emotional_trajectory=trajectory,
            notable_moments=moments,
            summary_text=summary_text,
        )
        self.db.add(digest)
        await self.db.commit()
        await self.db.refresh(digest)
        return digest
