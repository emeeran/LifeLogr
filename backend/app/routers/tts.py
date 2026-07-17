"""Text-to-speech endpoint using Edge TTS, with a disk cache.

Voice-quality / latency notes:

* Edge TTS escapes the input text, so SSML ``<break>`` tags can't be injected
  through ``Communicate`` for pacing. Instead we synthesize **chunk-by-chunk**
  (paragraph/sentence sized) directly into a single cache file and serve that
  file via ``FileResponse``. Serving a real file gives us HTTP ``Range`` support,
  which the Tauri webview (WebKit2GTK) needs to play ``<audio src>`` reliably —
  a ``StreamingResponse`` lacks Range and forces the frontend to buffer the whole
  blob first. The cache file is what makes both reliable playback and instant
  repeat reads possible.
* ``rate``, ``volume`` and ``pitch`` map to Edge TTS prosody. ``pitch`` is the
  extra lever — lower it for a warmer, deeper voice. All three are part of the
  cache key, so changing settings re-synthesizes under a new key.
* Background pre-warm (``/prewarm``) populates the cache when content is opened
  or saved, so audio is ready before the user hits read-aloud — zero perceived
  latency on the common path.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entry import Entry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])

DEFAULT_VOICE = "en-US-AvaNeural"

# Edge TTS handles long input, but chunking keeps synthesis responsive and tidies
# intonation at sentence boundaries.
_MAX_CHARS_PER_CHUNK = 500

# Inline LRU caps — "prewarm on open + save" grows the cache faster, so sweep it
# on each miss. Sized to comfortably cover a personal journal's re-readable
# entries without unbounded disk growth.
_MAX_CACHE_FILES = 1000
_MAX_CACHE_BYTES = 250 * 1024 * 1024

# Per-key synth locks — coalesce concurrent synth/prewarm for the same content
# so a prewarm race doesn't double-synthesize.
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


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

    Each chunk is at most ``max_chars`` long. Sentences are batched up to the
    limit rather than split one-per-chunk, to keep the number of Edge requests
    small.
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


def _cache_key(clean_text: str, voice: str, rate: float, volume: int, pitch: int) -> str:
    """Stable cache key from cleaned text + prosody params (sha1 hex)."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(voice.encode())
    h.update(b"\x00")
    h.update(f"{rate!r}\x00{volume!r}\x00{pitch!r}".encode())
    h.update(b"\x00")
    h.update(clean_text.encode())
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return settings.TTS_CACHE_DIR / f"{key}.mp3"


async def _get_lock(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


async def _synthesize_to_file(
    clean_text: str, voice: str, rate: str, volume: str, pitch: str, dest: Path
) -> None:
    """Synthesize cleaned text into ``dest`` (atomic: write .part then rename)."""
    try:
        import edge_tts
    except ImportError as exc:
        raise ImportError(
            "Text-to-speech requires the 'tts' extra. Install it with: "
            'uv pip install -e ".[tts]"'
        ) from exc

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with open(tmp, "wb") as f:
            for piece in _split_for_tts(clean_text):
                communicate = edge_tts.Communicate(
                    piece, voice, rate=rate, volume=volume, pitch=pitch
                )
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio" and chunk["data"]:
                        f.write(chunk["data"])
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _maybe_evict() -> None:
    """Best-effort LRU sweep: delete oldest .mp3 by mtime until under both caps."""
    try:
        cache_dir = settings.TTS_CACHE_DIR
        files = [p for p in cache_dir.glob("*.mp3")]
        count = len(files)
        size = sum(p.stat().st_size for p in files)
        if count <= _MAX_CACHE_FILES and size <= _MAX_CACHE_BYTES:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files:
            if count <= _MAX_CACHE_FILES and size <= _MAX_CACHE_BYTES:
                break
            try:
                sz = p.stat().st_size
                p.unlink()
                count -= 1
                size -= sz
            except OSError:
                pass
        logger.info("TTS cache evicted to %d files / %.1f MB", count, size / 1_048_576)
    except Exception:
        logger.warning("TTS cache eviction failed", exc_info=True)


async def _get_or_synthesize(
    clean_text: str, voice: str, rate: float, volume: int, pitch: int
) -> tuple[str, Path]:
    """Return (cache_key, path) for the synthesized audio, synthesizing if missing.

    Concurrent synth for the same key is coalesced via a per-key lock, so a
    background prewarm racing a foreground play request synthesizes once.
    """
    key = _cache_key(clean_text, voice, rate, volume, pitch)
    path = _cache_path(key)
    if path.is_file():
        return key, path
    async with await _get_lock(key):
        if path.is_file():  # re-check after acquiring the lock
            return key, path
        await _synthesize_to_file(
            clean_text, voice, _rate_str(rate), _volume_str(volume), _pitch_str(pitch), path
        )
        _maybe_evict()
        return key, path


async def _bg_prewarm(
    clean_text: str, voice: str, rate: float, volume: int, pitch: int
) -> None:
    """Detached background synthesis — swallows errors (prewarm is best-effort)."""
    try:
        await _get_or_synthesize(clean_text, voice, rate, volume, pitch)
    except Exception:
        logger.warning("TTS prewarm failed", exc_info=True)


def _entry_text(entry: Entry) -> str:
    parts = [t for t in [entry.title, entry.body] if t]
    return "\n\n".join(parts)


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
    """Synthesize (or serve cached) speech for an entry as a Range-capable MP3."""
    result = await db.execute(select(Entry).where(Entry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Entry {entry_id} not found")

    clean = _clean_markdown(_entry_text(entry))
    if not clean:
        return Response(content=b"", media_type="audio/mpeg")

    try:
        _key, path = await _get_or_synthesize(clean, voice, rate, volume, pitch)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("TTS entry generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Text-to-speech failed: {exc}. Edge TTS needs internet access.",
        ) from exc

    return FileResponse(path=str(path), media_type="audio/mpeg", filename="tts.mp3")


class SpeakRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    rate: float = Field(1.0, ge=0.5, le=2.0)
    volume: int = Field(100, ge=0, le=100)
    pitch: int = Field(0, ge=-100, le=100)


@router.post("/speak")
async def speak_text(req: SpeakRequest) -> dict[str, Any]:
    """Synthesize (or serve cached) arbitrary text; return the cache key to play."""
    clean = _clean_markdown(req.text)
    if not clean:
        return {"key": ""}

    try:
        key, _path = await _get_or_synthesize(clean, req.voice, req.rate, req.volume, req.pitch)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("TTS generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Text-to-speech failed: {exc}. Edge TTS needs internet access.",
        ) from exc

    return {"key": key}


_KEY_RE = re.compile(r"^[0-9a-f]{40}$")


@router.get("/file/{key}")
async def speak_file(key: str) -> Response:
    """Serve a previously-synthesized cache file (Range-capable). 404 if missing.

    Synthesis never happens here — callers use ``/entry/{id}``, ``/speak``, or
    ``/prewarm`` to populate the cache, so this stays a fast file serve.
    """
    if not _KEY_RE.match(key):
        raise HTTPException(status_code=404, detail="Not found")
    path = _cache_path(key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path=str(path), media_type="audio/mpeg", filename="tts.mp3")


class PrewarmRequest(BaseModel):
    entry_id: int | None = None
    text: str | None = None
    voice: str = DEFAULT_VOICE
    rate: float = Field(1.0, ge=0.5, le=2.0)
    volume: int = Field(100, ge=0, le=100)
    pitch: int = Field(0, ge=-100, le=100)


@router.post("/prewarm")
async def prewarm(
    req: PrewarmRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Background-synthesize content so read-aloud is instant when requested.

    Returns ``{"cached": true}`` (200) if already cached, else schedules a
    detached synthesis task and returns ``{"cached": false}`` (202).
    """
    if req.entry_id is not None:
        result = await db.execute(select(Entry).where(Entry.id == req.entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Entry {req.entry_id} not found")
        clean = _clean_markdown(_entry_text(entry))
    elif req.text is not None:
        clean = _clean_markdown(req.text)
    else:
        raise HTTPException(status_code=422, detail="Provide entry_id or text")

    if not clean:
        return {"cached": True}

    key = _cache_key(clean, req.voice, req.rate, req.volume, req.pitch)
    if _cache_path(key).is_file():
        return {"cached": True}

    asyncio.create_task(_bg_prewarm(clean, req.voice, req.rate, req.volume, req.pitch))
    return {"cached": False}
