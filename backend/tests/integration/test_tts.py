"""Tests for the TTS cache, FileResponse serving, and prewarm.

Edge TTS is network-bound, so we inject a fake ``edge_tts`` module into
``sys.modules`` (the router imports it lazily) and assert against the cache
files it writes. No real synthesis happens.
"""

import asyncio
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from app.models.entry import Entry
from app.routers import tts


def _install_fake_edge_tts(monkeypatch) -> dict:
    """Install a fake edge_tts module; return a dict counting Communicate() calls."""
    calls = {"n": 0}

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            self.text = text
            self.voice = voice
            calls["n"] += 1

        async def stream(self):
            yield {"type": "audio", "data": b"MP3DATA:" + self.text.encode()[:16]}
            yield {"type": "WordBoundary", "data": None}  # non-audio → skipped

    async def list_voices():
        return [
            {"ShortName": "en-US-AvaNeural", "Locale": "en-US", "Gender": "Female"},
            {"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB", "Gender": "Female"},
        ]

    fake = SimpleNamespace(Communicate=FakeCommunicate, list_voices=list_voices)
    monkeypatch.setitem(sys.modules, "edge_tts", fake)
    return calls


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the TTS cache to a per-test temp dir."""
    monkeypatch.setattr(tts.settings, "TTS_CACHE_DIR", tmp_path)
    return tmp_path


class TestCacheKey:
    def test_deterministic(self):
        k1 = tts._cache_key("hello world", "en-US-AvaNeural", 1.0, 100, 0)
        k2 = tts._cache_key("hello world", "en-US-AvaNeural", 1.0, 100, 0)
        assert k1 == k2
        assert len(k1) == 40  # sha1 hex

    def test_sensitive_to_voice(self):
        a = tts._cache_key("hi", "en-US-AvaNeural", 1.0, 100, 0)
        b = tts._cache_key("hi", "en-GB-SoniaNeural", 1.0, 100, 0)
        assert a != b

    def test_sensitive_to_prosody(self):
        a = tts._cache_key("hi", "en-US-AvaNeural", 1.0, 100, 0)
        b = tts._cache_key("hi", "en-US-AvaNeural", 1.5, 100, 0)
        assert a != b

    def test_uses_cleaned_text(self):
        # Markdown cruft must not change the key (cleaning is part of the key).
        a = tts._cache_key(tts._clean_markdown("# Hello"), "v", 1.0, 100, 0)
        b = tts._cache_key(tts._clean_markdown("Hello"), "v", 1.0, 100, 0)
        assert a == b


class TestGetOrSynthesize:
    async def test_miss_then_hit(self, cache_dir, monkeypatch):
        calls = _install_fake_edge_tts(monkeypatch)
        key1, path1 = await tts._get_or_synthesize("hello world", "v", 1.0, 100, 0)
        assert path1.is_file()
        assert path1.read_bytes().startswith(b"MP3DATA:")
        assert calls["n"] == 1

        # Second call is a cache hit — no new synthesis.
        key2, path2 = await tts._get_or_synthesize("hello world", "v", 1.0, 100, 0)
        assert key2 == key1
        assert path2 == path1
        assert calls["n"] == 1

    async def test_coalesces_concurrent_same_key(self, cache_dir, monkeypatch):
        calls = _install_fake_edge_tts(monkeypatch)
        # Two concurrent synth requests for the same key → synthesized once.
        (k1, p1), (k2, p2) = await asyncio.gather(
            tts._get_or_synthesize("same text", "v", 1.0, 100, 0),
            tts._get_or_synthesize("same text", "v", 1.0, 100, 0),
        )
        assert k1 == k2 and p1 == p2 and p1.is_file()
        assert calls["n"] == 1


class TestEviction:
    def test_evicts_oldest_over_cap(self, cache_dir, monkeypatch):
        import os

        monkeypatch.setattr(tts, "_MAX_CACHE_FILES", 2)
        monkeypatch.setattr(tts, "_MAX_CACHE_BYTES", 10 * 1024 * 1024)

        d = tts.settings.TTS_CACHE_DIR
        # Three cache files with strictly increasing mtimes (oldest → newest).
        paths = []
        for i in range(3):
            p = d / f"{i:040x}.mp3"
            p.write_bytes(b"x")
            ts = 1_700_000_000 + i
            os.utime(p, (ts, ts))
            paths.append(p)

        tts._maybe_evict()
        remaining = list(d.glob("*.mp3"))
        assert len(remaining) == 2
        # Oldest (index 0) evicted; newest two kept.
        assert not paths[0].exists()
        assert paths[1].exists() and paths[2].exists()


class TestSpeakEndpoint:
    async def test_speak_returns_key_and_file_serves(self, client, cache_dir, monkeypatch):
        _install_fake_edge_tts(monkeypatch)
        resp = await client.post("/api/v1/tts/speak", json={"text": "Hello there."})
        assert resp.status_code == 200
        key = resp.json()["key"]
        assert len(key) == 40

        audio = await client.get(f"/api/v1/tts/file/{key}")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/mpeg")
        assert audio.content.startswith(b"MP3DATA:")

    async def test_file_404_when_missing(self, client, cache_dir):
        missing = "0" * 40
        resp = await client.get(f"/api/v1/tts/file/{missing}")
        assert resp.status_code == 404

    async def test_file_404_for_non_hex_key(self, client, cache_dir):
        # The key regex only accepts 40 hex chars; anything else → 404.
        # (Routing is also single-segment, so encoded slashes can't traverse.)
        resp = await client.get("/api/v1/tts/file/not-hex-at-all")
        assert resp.status_code == 404
        resp2 = await client.get("/api/v1/tts/file/abc")  # too short
        assert resp2.status_code == 404

    async def test_speak_blank_returns_empty_key(self, client, cache_dir, monkeypatch):
        _install_fake_edge_tts(monkeypatch)
        resp = await client.post("/api/v1/tts/speak", json={"text": "   "})
        assert resp.status_code == 200
        assert resp.json() == {"key": ""}


class TestPrewarm:
    async def test_schedules_then_cached(self, client, cache_dir, monkeypatch):
        _install_fake_edge_tts(monkeypatch)
        # First prewarm → not cached yet, schedules background synth → 202 body.
        r1 = await client.post("/api/v1/tts/prewarm", json={"text": "warm me up"})
        assert r1.status_code == 200
        assert r1.json() == {"cached": False}

        # Let the detached task finish (fake synth is instant; one tick suffices).
        key = tts._cache_key(tts._clean_markdown("warm me up"), "en-US-AvaNeural", 1.0, 100, 0)
        for _ in range(50):
            if tts._cache_path(key).is_file():
                break
            await asyncio.sleep(0.01)
        assert tts._cache_path(key).is_file(), "prewarm did not populate the cache"

        # Second prewarm → already cached → 200 body.
        r2 = await client.post("/api/v1/tts/prewarm", json={"text": "warm me up"})
        assert r2.json() == {"cached": True}

    async def test_requires_entry_or_text(self, client, cache_dir):
        resp = await client.post("/api/v1/tts/prewarm", json={})
        assert resp.status_code == 422


class TestEntryEndpoint:
    async def test_serves_entry_audio(self, client, db_session, cache_dir, monkeypatch):
        _install_fake_edge_tts(monkeypatch)
        entry = Entry(entry_date=date.today(), title="My Day", body="I had a good day.")
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        resp = await client.get(f"/api/v1/tts/entry/{entry.id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("audio/mpeg")
        assert resp.content  # non-empty body

    async def test_missing_entry_404(self, client, cache_dir):
        resp = await client.get("/api/v1/tts/entry/999999")
        assert resp.status_code == 404


class TestVoices:
    async def test_list_voices(self, client, monkeypatch):
        _install_fake_edge_tts(monkeypatch)
        resp = await client.get("/api/v1/tts/voices")
        assert resp.status_code == 200
        names = [v["short_name"] for v in resp.json()]
        assert "en-US-AvaNeural" in names
