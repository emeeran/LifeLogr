"""Text-to-speech endpoint using Edge TTS.

Voice-quality notes:

* Edge TTS escapes the input text, so SSML ``<break>`` tags can't be injected
  through ``Communicate`` for pacing. Instead we synthesize **chunk-by-chunk**
  (paragraph/sentence sized) and stream the MP3 straight back. That keeps the
  first audio near-instant, lets the whole long entry/email be read (no Edge
  truncation or receive-timeout on big payloads), and gives cleaner intonation
  at sentence boundaries.
* ``rate``, ``volume`` and ``pitch`` map to Edge TTS prosody. ``pitch`` is the
  extra lever — lower it for a warmer, deeper voice.
"""

from __future__ import annotations

import html
import io
import logging
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entry import Entry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])

DEFAULT_VOICE = "en-US-AvaNeural"

# Edge TTS handles long input, but chunking keeps first-audio latency low,
# avoids receive timeouts on very long entries/emails, and tidies intonation.
_MAX_CHARS_PER_CHUNK = 500


def _clean_markdown(text: str) -> str:
    """Strip markdown / HTML cruft so it isn't read aloud, preserving paragraphs."""
    # Raw HTML tags (e.g. leftovers from HTML emails) — strip before entity decode.
    text = re.sub(r"<[^>]+>", " ", text)
    # Markdown headings / emphasis / code / images / links / list markers / quotes / rules.
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"---+", "", text)
    # Decode entities (&amp; → &) so Edge doesn't say "amp".
    text = html.unescape(text)
    # Collapse runs of spaces/tabs and trim line indentation; keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_for_tts(text: str, max_chars: int = _MAX_CHARS_PER_CHUNK) -> list[str]:
    """Split text into synthesis-sized chunks at paragraph/sentence boundaries.

    Each chunk is at most ``max_chars`` long, so synthesis stays responsive and
    Edge TTS never receives a payload large enough to time out. Sentences are
    batched up to the limit rather than split one-per-chunk, to keep the number
    of network round-trips small.
    """
    chunks: list[str] = []

    def hard_split(sentence: str) -> None:
        """Word-split a single over-long sentence into ≤max_chars pieces."""
        part = ""
        for word in sentence.split():
            if len(part) + len(word) + 1 <= max_chars:
                part = f"{part} {word}".strip()
            else:
                if part:
                    chunks.append(part)
                part = word
        if part:
            chunks.append(part)

    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        # Long paragraph → batch sentence-ish pieces up to max_chars.
        buf = ""
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                if buf:
                    chunks.append(buf)
                    buf = ""
                hard_split(sentence)
                continue
            if len(buf) + len(sentence) + 1 <= max_chars:
                buf = f"{buf} {sentence}".strip()
            else:
                if buf:
                    chunks.append(buf)
                buf = sentence
        if buf:
            chunks.append(buf)

    return chunks or [text]


def _rate_str(speed: float) -> str:
    """Convert a speed multiplier (0.5-2.0) to an Edge TTS rate string."""
    return f"{int((speed - 1.0) * 100):+d}%"


def _volume_str(volume_pct: int) -> str:
    """Convert volume percentage (0-100) to an Edge TTS volume string."""
    return f"{int((volume_pct - 50) * 2):+d}%"


def _pitch_str(pitch: int) -> str:
    """Convert a pitch offset to an Edge TTS pitch string (Hz). 0 = unchanged."""
    return f"{pitch:+d}Hz"


async def _stream_audio(
    text: str, voice: str, rate: str, volume: str, pitch: str
) -> AsyncIterator[bytes]:
    """Yield MP3 bytes for ``text``, synthesizing chunk-by-chunk."""
    try:
        import edge_tts
    except ImportError as exc:
        raise ImportError(
            "Text-to-speech requires the 'tts' extra. Install it with: "
            'uv pip install -e ".[tts]"'
        ) from exc

    for piece in _split_for_tts(text):
        communicate = edge_tts.Communicate(piece, voice, rate=rate, volume=volume, pitch=pitch)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and chunk["data"]:
                buf.write(chunk["data"])
        data = buf.getvalue()
        if data:
            yield data


async def _audio_response(
    text: str, voice: str, rate: float, volume: int, pitch: int
) -> Response:
    """Build a streaming MP3 response, or an empty body for blank text.

    The first chunk is synthesized eagerly so import/connect errors surface as
    proper HTTP errors (caught by the route) instead of a truncated stream.
    """
    clean = _clean_markdown(text)
    if not clean:
        return Response(content=b"", media_type="audio/mpeg")

    gen = _stream_audio(clean, voice, _rate_str(rate), _volume_str(volume), _pitch_str(pitch))
    try:
        first = await gen.__anext__()
    except StopAsyncIteration:
        return Response(content=b"", media_type="audio/mpeg")

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for rest in gen:
            yield rest

    return StreamingResponse(body(), media_type="audio/mpeg")


@router.get("/voices")
async def list_voices() -> Any:
    """List available Edge TTS voices."""
    try:
        import edge_tts
    except ImportError as exc:
        raise ImportError(
            "Text-to-speech requires the 'tts' extra. Install it with: "
            'uv pip install -e ".[tts]"'
        ) from exc

    voices = await edge_tts.list_voices()
    return [
        {"short_name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
        for v in voices
    ]


@router.get("/entry/{entry_id}")
async def speak_entry(
    entry_id: int,
    voice: str = Query(DEFAULT_VOICE),
    rate: float = Query(1.0, ge=0.5, le=2.0),
    volume: int = Query(100, ge=0, le=100),
    pitch: int = Query(0, ge=-100, le=100),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate speech audio for an entry and stream it back as MP3."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Entry {entry_id} not found")

    parts = [t for t in [entry.title, entry.body] if t]
    try:
        return await _audio_response("\n\n".join(parts), voice, rate, volume, pitch)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("TTS entry generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Text-to-speech failed: {exc}. Edge TTS needs internet access.",
        ) from exc


class SpeakRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    rate: float = Field(1.0, ge=0.5, le=2.0)
    volume: int = Field(100, ge=0, le=100)
    pitch: int = Field(0, ge=-100, le=100)


@router.post("/speak")
async def speak_text(req: SpeakRequest) -> Response:
    """Generate speech audio from arbitrary text and stream it back as MP3."""
    try:
        return await _audio_response(req.text, req.voice, req.rate, req.volume, req.pitch)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("TTS generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Text-to-speech failed: {exc}. Edge TTS needs internet access.",
        ) from exc
