"""Opt-in weather auto-fill for geotagged entries — Open-Meteo daily conditions.

When ``WEATHER_ENABLED`` is on (it is off by default), saving an entry that has
coordinates schedules a detached task that fetches that day's conditions from
Open-Meteo (no key, no account) and stores them as an ``EntryEvent`` with
``kind="weather"`` — the same rows the Diarium importer writes, so the entry
detail view renders them with no new UI.

Privacy posture (mirrored in the egress report, ``routers/system.py``):

- Only the coordinates, **rounded to 2 decimals (~1 km)**, and the entry date
  are sent. Entry text never leaves the device.
- Responses are cached on disk under ``DATA_DIR/weather`` keyed by the rounded
  coordinates + date; past daily observations are immutable, so cache entries
  need no TTL.

The import pipeline deliberately never schedules weather: bulk imports stay
network-free (``EntryService.create(commit=False)`` bypasses the post-save
hooks entirely).

Disk-cache style follows ``routers/tts.py`` (atomic ``.part`` + ``os.replace``
writes, per-key locks to coalesce concurrent fetches) with one documented
divergence: cache files use readable ``{lat}_{lng}_{date}.json`` names rather
than sha1 keys — the cardinality is tiny, the parameters are not secret, and a
debuggable name is worth more here than a hashed one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import settings

logger = logging.getLogger(__name__)

# Open-Meteo's forecast API only serves observed past weather for a bounded
# window (~92 days). Older entry dates would 400, so they are skipped without a
# request — historical backfill stays out of scope by construction.
_MAX_PAST_DAYS = 92
_HTTP_TIMEOUT = 10.0
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather-interpretation codes (Open-Meteo's ``weather_code`` daily field).
_WMO_LABELS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# Track pending weather tasks for graceful shutdown.
_pending_tasks: set[asyncio.Task[None]] = set()

# Per-key locks coalesce concurrent fetches for the same place+date. Cardinality
# is small (one key per rounded-coordinate day ever saved while enabled), but
# bound it anyway: past the cap, unlocked locks are dropped — a fetcher that
# loses its lock simply re-checks the cache afterwards, which is always safe.
_fetch_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
_MAX_FETCH_LOCKS = 64
_locks_guard = asyncio.Lock()


def round_coord(value: float) -> float:
    """Round a coordinate to 2 decimals (~1 km) — the precision that leaves the device."""
    return round(float(value), 2)


def _as_date(value: date | datetime | str) -> date | None:
    """Normalize an entry date (ORM ``date``, ``datetime``, or ISO string)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _cache_path(lat: float, lng: float, day: date) -> Any:
    lat_r, lng_r = round_coord(lat), round_coord(lng)
    return settings.WEATHER_CACHE_DIR / f"{lat_r:+.2f}_{lng_r:+.2f}_{day.isoformat()}.json"


def _content_and_label(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Extract ``(content, label)`` — e.g. ``("84 / 74 °F", "Partly cloudy")``.

    Same shape the Diarium importer writes for ``Events.Type=0`` rows.
    """
    daily = (payload or {}).get("daily") or {}
    highs, lows, codes = daily.get("temperature_2m_max"), daily.get("temperature_2m_min"), daily.get("weather_code")
    if not (isinstance(highs, list) and isinstance(lows, list) and highs and lows):
        return None
    try:
        hi, lo = round(float(highs[0])), round(float(lows[0]))
        code = int(codes[0]) if isinstance(codes, list) and codes else 0
    except (TypeError, ValueError, IndexError):
        return None
    label = _WMO_LABELS.get(code, f"Unknown ({code})")
    return (f"{hi} / {lo} °F", label)


def _request_params(lat: float, lng: float, day: date) -> dict[str, str] | None:
    """Query params for one day at the rounded coordinates; ``None`` to skip.

    Older than the observed-past window → ``None`` (no request, no error):
    backfilling history is explicitly out of scope for weather auto-fill.
    """
    if day < date.today() - timedelta(days=_MAX_PAST_DAYS):
        return None
    return {
        "latitude": f"{round_coord(lat):.2f}",
        "longitude": f"{round_coord(lng):.2f}",
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }


async def _get_lock(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _fetch_locks.get(key)
        if lock is not None:
            _fetch_locks.move_to_end(key)  # LRU touch
            return lock
        while len(_fetch_locks) >= _MAX_FETCH_LOCKS:
            for old_key, old_lock in _fetch_locks.items():
                if not old_lock.locked():
                    _fetch_locks.pop(old_key, None)
                    break
            else:
                break  # everything is in use — leave the map as is
        lock = asyncio.Lock()
        _fetch_locks[key] = lock
        return lock


async def _fetch(lat: float, lng: float, day: date, dest: Path) -> tuple[str, str] | None:
    """Fetch conditions from Open-Meteo and atomically cache them at *dest*."""
    params = _request_params(lat, lng, day)
    if params is None:
        return None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(_OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        result = _content_and_label(resp.json())
    if result is None:
        return None
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_text(json.dumps({"content": result[0], "label": result[1]}))
        os.replace(tmp, dest)
    except OSError:
        logger.warning("Weather cache write failed for %s", dest.name, exc_info=True)
    return result


async def conditions_for(lat: float, lng: float, day: date | datetime | str) -> tuple[str, str] | None:
    """Return ``(content, label)`` for the day at the coordinates, or ``None``.

    Disk-cache first; on a miss, one Open-Meteo request (rounded coordinates
    only). Any network or parse failure logs a warning and returns ``None`` —
    a weather miss must never fail an entry save.
    """
    normalized = _as_date(day)
    if normalized is None:
        return None
    path = _cache_path(lat, lng, normalized)
    if path.is_file():
        try:
            cached = json.loads(path.read_text())
            return cached["content"], cached["label"]
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt/empty cache file: drop it and fall through to a refetch.
            try:
                path.unlink()
            except OSError:
                pass
    key = path.name
    async with await _get_lock(key):
        if path.is_file():  # re-check after acquiring the lock
            try:
                cached = json.loads(path.read_text())
                return cached["content"], cached["label"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            return await _fetch(lat, lng, normalized, path)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Weather fetch failed for %s: %s", key, exc)
            return None


class WeatherService:
    """Schedules the detached post-save weather fetch (mirrors EnrichmentService)."""

    @staticmethod
    def schedule(entry_id: int, latitude: float | None, longitude: float | None, entry_date: Any) -> None:
        """Fire-and-forget weather fetch. Does not block the save response.

        Callers guard on ``settings.WEATHER_ENABLED`` + coordinates; re-checked
        here so a mid-flight settings toggle cannot start a stray fetch.
        """
        if not settings.WEATHER_ENABLED or latitude is None or longitude is None:
            return
        day = _as_date(entry_date)
        if day is None:
            return
        task = asyncio.create_task(_run_weather(entry_id, latitude, longitude, day))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)


async def cancel_pending() -> None:
    """Cancel all outstanding weather tasks (for graceful shutdown)."""
    for task in _pending_tasks:
        task.cancel()
    if _pending_tasks:
        await asyncio.gather(*_pending_tasks, return_exceptions=True)
    _pending_tasks.clear()


async def _run_weather(entry_id: int, latitude: float, longitude: float, day: date) -> None:
    """Resolve conditions and store the ``EntryEvent`` on a fresh session.

    Idempotent on update: an entry that already carries a weather event (or was
    deleted / encrypted in the meantime) is left untouched. Opened lazily so a
    repointed ``app.core.database.async_session`` (tests, restores) is followed.
    """
    from app.core.database import async_session

    try:
        result = await conditions_for(latitude, longitude, day)
        if result is None:
            return
        content, label = result

        from app.models.entry import Entry
        from app.models.entry_event import KIND_WEATHER, EntryEvent

        async with async_session() as session:
            entry = await session.get(Entry, entry_id)
            if entry is None or entry.is_encrypted:
                return
            existing = (
                await session.execute(
                    select(EntryEvent.id)
                    .where(EntryEvent.entry_id == entry_id)
                    .where(EntryEvent.kind == KIND_WEATHER)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                EntryEvent(entry_id=entry_id, kind=KIND_WEATHER, content=content, label=label)
            )
            await session.commit()
        logger.info("Weather stored for entry %d (%s)", entry_id, label)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Weather auto-fill failed for entry %d", entry_id)
