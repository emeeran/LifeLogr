"""Memorial dedication audio — plays the bundled Garden.mp3 via a system player.

Browsers block unmuted autoplay on a cold page load (no prior user gesture), so
the dedication splash can't reliably start audio from JavaScript. Instead the
local desktop backend spawns an audio player for the bundled track through the
system audio server, which is not subject to the browser's autoplay policy at
all. The frontend starts playback when the splash appears and stops it when the
splash dismisses; if no player is installed it falls back to in-browser audio.

Security: the subprocess takes **no user input** — a fixed player binary and the
bundled track path, passed as an argv list (never a shell). The endpoints are
loopback-only like the other single-user desktop endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memorial", tags=["memorial"])

# Resolve the bundled track without importing app.main (avoids a circular import
# during router registration). backend/app/routers → backend/app → backend → root.
_ROOT = Path(__file__).resolve().parents[3]
_TRACK_PATHS = [
    _ROOT / "frontend" / "dist" / "Garden.mp3",
    _ROOT / "frontend" / "public" / "Garden.mp3",
]


def _resolve_track() -> Path | None:
    for candidate in _TRACK_PATHS:
        if candidate.is_file():
            return candidate
    return None


# Players we know how to drive, in priority order. Each builder returns the full
# argv list to play *track* (no shell). The first binary found on $PATH wins.
def _ffplay(track: Path) -> list[str]:
    # -nodisp: no SDL video window. -autoexit: quit when the track ends.
    return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", str(track)]


def _cvlc(track: Path) -> list[str]:
    return ["cvlc", "--play-and-exit", "--no-video", "--quiet", str(track)]


def _vlc(track: Path) -> list[str]:
    return ["vlc", "-I", "dummy", "--play-and-exit", "--no-video", "--quiet", str(track)]


def _mpg123(track: Path) -> list[str]:
    return ["mpg123", "-q", str(track)]


def _sox(track: Path) -> list[str]:
    return ["play", "-q", str(track)]


_PLAYERS: list[tuple[str, Callable[[Path], list[str]]]] = [
    ("ffplay", _ffplay),
    ("cvlc", _cvlc),
    ("vlc", _vlc),
    ("mpg123", _mpg123),
    ("play", _sox),
]


def _pick_player() -> tuple[str, Callable[[Path], list[str]]] | None:
    for name, builder in _PLAYERS:
        if shutil.which(name):
            return name, builder
    return None


# Active player process. Spawned in its own session/process group so we can kill
# it (and any helper it forked) cleanly on stop.
_lock = asyncio.Lock()
_proc: asyncio.subprocess.Process | None = None


async def _stop_locked() -> None:
    """Terminate the active player (idempotent, no-op if none)."""
    global _proc
    proc = _proc
    if proc is None:
        return
    _proc = None
    if proc.returncode is not None:
        return  # already exited
    try:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
            return
        except asyncio.TimeoutError:
            pass
        # Didn't die on SIGTERM — force it.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        await asyncio.wait_for(proc.wait(), timeout=1)
    except Exception:
        logger.warning("Failed to stop memorial audio", exc_info=True)


def _force_kill_sync() -> None:
    """Best-effort synchronous kill for atexit / abnormal shutdown."""
    proc = _proc
    if proc is None or proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    except Exception:
        logger.warning("Failed to force-kill memorial audio on exit", exc_info=True)


@router.post("/audio/start")
async def start_audio() -> dict[str, Any]:
    """Start the memorial track on the system audio device.

    Returns ``{"mode": "system", "player": <name>}`` when a player was launched
    (the frontend then does nothing more — the backend owns playback). Returns
    ``{"mode": "browser", ...}`` when playback isn't possible server-side (no
    player installed, no track, or spawn failure), signalling the frontend to
    fall back to its in-browser ``<audio>`` attempt.
    """
    global _proc

    track = _resolve_track()
    if track is None:
        logger.info("Memorial track not found; frontend will use browser fallback")
        return {"mode": "browser", "reason": "track-not-found"}

    player = _pick_player()
    if player is None:
        logger.info("No system audio player found; memorial audio will use browser fallback")
        return {"mode": "browser", "reason": "no-player"}

    name, builder = player
    async with _lock:
        await _stop_locked()  # tear down any player still running
        try:
            _proc = await asyncio.create_subprocess_exec(
                *builder(track),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,  # own process group → clean kill on stop
            )
        except Exception:
            logger.warning("Failed to start memorial audio player (%s)", name, exc_info=True)
            _proc = None
            return {"mode": "browser", "reason": "spawn-failed"}

    logger.info("Memorial audio started via %s (pid=%s)", name, _proc.pid)
    return {"mode": "system", "player": name}


@router.post("/audio/stop")
async def stop_audio() -> dict[str, bool]:
    """Stop the memorial track if the backend is playing it (idempotent)."""
    async with _lock:
        await _stop_locked()
    return {"stopped": True}


# If the tab/app is closed mid-splash, the frontend never calls /stop. Tear down
# any lingering player when the interpreter exits so audio doesn't outlive it
# (ffplay -autoexit would end on its own, but this covers vlc/mpg123/sox too).
import atexit

atexit.register(_force_kill_sync)
