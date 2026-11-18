"""``dir_size`` caching — the settings endpoint must not walk the media tree
on every request."""

from pathlib import Path

from app.services import settings_service as ss


class TestDirSizeCache:
    def test_repeated_calls_within_ttl_do_not_rewalk(self, tmp_path: Path, monkeypatch):
        calls = {"n": 0}
        real_scandir = ss.os.scandir

        def counting_scandir(path):
            calls["n"] += 1
            return real_scandir(path)

        monkeypatch.setattr(ss.os, "scandir", counting_scandir)
        (tmp_path / "a.txt").write_bytes(b"x" * 10)
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_bytes(b"y" * 20)

        first = ss.dir_size(tmp_path)
        assert first == 30
        walks_after_first = calls["n"]

        (tmp_path / "c.txt").write_bytes(b"z" * 5)
        assert ss.dir_size(tmp_path) == first  # cached — new file invisible
        assert calls["n"] == walks_after_first  # and no second walk happened

    def test_max_age_zero_forces_a_fresh_walk(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"x" * 10)
        assert ss.dir_size(tmp_path) == 10
        (tmp_path / "b.txt").write_bytes(b"y" * 5)
        assert ss.dir_size(tmp_path, max_age_seconds=0) == 15

    def test_missing_directory_is_zero(self, tmp_path: Path):
        assert ss.dir_size(tmp_path / "nope") == 0

    def test_cache_is_per_path(self, tmp_path: Path):
        (tmp_path / "one").mkdir()
        (tmp_path / "two").mkdir()
        (tmp_path / "one" / "f").write_bytes(b"a" * 7)
        (tmp_path / "two" / "f").write_bytes(b"b" * 3)
        assert ss.dir_size(tmp_path / "one") == 7
        assert ss.dir_size(tmp_path / "two") == 3

    def test_ttl_expiry_rewalks(self, tmp_path: Path, monkeypatch):
        (tmp_path / "a.txt").write_bytes(b"x")
        assert ss.dir_size(tmp_path) == 1
        # Age the cached entry past any TTL and confirm the walk re-runs.
        real_monotonic = ss.time.monotonic
        monkeypatch.setattr(ss.time, "monotonic", lambda: real_monotonic() + 3600)
        (tmp_path / "b.txt").write_bytes(b"yy")
        assert ss.dir_size(tmp_path, max_age_seconds=60) == 3
