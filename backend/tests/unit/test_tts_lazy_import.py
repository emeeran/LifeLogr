"""TTS import-graph laziness (LW-5).

``edge_tts`` pulls in the whole aiohttp chain, and sounddevice/soundfile pull
in PortAudio — none of them may load at app startup. They are imported inside
the functions that need them, so the assertions here hold against the real
import system: if someone hoists an import to module level, these tests fail.
"""

import sys
from types import SimpleNamespace

import pytest

from app.routers import tts

_HEAVY_MODULES = ("edge_tts", "aiohttp", "sounddevice", "soundfile")


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the TTS cache to a per-test temp dir."""
    monkeypatch.setattr(tts.settings, "TTS_CACHE_DIR", tmp_path)
    return tmp_path


def test_heavy_audio_modules_absent_after_app_import() -> None:
    """Importing the app (routers included) must not load edge_tts/aiohttp or
    the recording stack — they stay out of the startup import graph.

    Runs in a fresh interpreter: sibling tests legitimately lazy-import these
    modules, and sys.modules is process-global, so an in-process assertion
    would be order-dependent."""
    code = (
        "import sys; sys.path.insert(0, '.')\n"
        "import app.main  # noqa: F401\n"
        f"loaded = [m for m in {_HEAVY_MODULES!r} if m in sys.modules]\n"
        "assert not loaded, f'imported at startup: {loaded}'\n"
    )
    import subprocess

    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=".",
        timeout=60,
    )
    assert result.returncode == 0, f"startup import graph pulled in heavy modules:\n{result.stderr}"


def test_edge_tts_absent_before_synthesize(cache_dir, monkeypatch) -> None:
    """No synthesize call → no edge_tts in sys.modules (the router module itself
    imports cleanly without it)."""
    monkeypatch.setattr(tts.settings, "TTS_CACHE_DIR", cache_dir)
    assert "edge_tts" not in sys.modules
    # A cache-hit lookup exercises the module without touching the import.
    key = tts._cache_key("never synthesized", "v", 1.0, 100, 0)
    assert tts._cache_path(key).is_file() is False


async def test_edge_tts_loaded_after_synthesize(cache_dir, monkeypatch) -> None:
    """The first synthesize call imports edge_tts (here: a fake installed into
    sys.modules) — the lazy import happens exactly at the synthesize boundary."""
    monkeypatch.setattr(tts.settings, "TTS_CACHE_DIR", cache_dir)
    assert "edge_tts" not in sys.modules

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            self.text = text

        async def stream(self):
            yield {"type": "audio", "data": b"MP3DATA"}

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))

    await tts._get_or_synthesize("hello lazy", "v", 1.0, 100, 0)

    assert "edge_tts" in sys.modules  # only after the synthesize call
