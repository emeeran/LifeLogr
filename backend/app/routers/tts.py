"""Text-to-speech endpoint using Edge TTS."""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entry import Entry

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])

DEFAULT_VOICE = "en-US-AvaNeural"


def _clean_markdown(text: str) -> str:
    import re

    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"---+", "", text)
    return text.strip()


async def _generate_audio(text: str, voice: str) -> bytes:
    """Generate MP3 audio bytes from text using Edge TTS."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


@router.get("/voices")
async def list_voices() -> Any:
    """List available Edge TTS voices."""
    import edge_tts

    voices = await edge_tts.list_voices()
    return [
        {"short_name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
        for v in voices
    ]


@router.get("/entry/{entry_id}")
async def speak_entry(
    entry_id: int,
    voice: str = Query(DEFAULT_VOICE),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Generate speech audio for an entry and stream it back as MP3."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Entry {entry_id} not found")

    parts = [t for t in [entry.title, entry.body] if t]
    text = _clean_markdown("\n\n".join(parts))

    if not text:
        return Response(content=b"", media_type="audio/mpeg")

    audio = await _generate_audio(text, voice)
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")


class SpeakRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE


@router.post("/speak")
async def speak_text(req: SpeakRequest) -> StreamingResponse:
    """Generate speech audio from arbitrary text and stream it back as MP3."""
    text = _clean_markdown(req.text)

    if not text:
        return Response(content=b"", media_type="audio/mpeg")

    audio = await _generate_audio(text, req.voice)
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")
