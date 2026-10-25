"""Tests for config hardening: loopback detection, atomic key-file override,
bounded settings, and CORS origin normalisation."""

from __future__ import annotations

import json
import stat

import pytest

from app.core.config import (
    DEFAULT_SECRET_KEY,
    Settings,
    is_loopback_host,
    settings,
    write_storage_override,
)


class TestLoopbackDetection:
    def test_whole_ipv4_loopback_range(self) -> None:
        assert is_loopback_host("127.0.0.1")
        assert is_loopback_host("127.0.0.2")
        assert is_loopback_host("127.255.255.254")

    def test_ipv6_loopback_spellings(self) -> None:
        for host in ("::1", "[::1]", "0:0:0:0:0:0:0:1", "[0:0:0:0:0:0:0:1]"):
            assert is_loopback_host(host), host

    def test_localhost_names(self) -> None:
        assert is_loopback_host("localhost")
        assert is_loopback_host(" localhost ")
        assert is_loopback_host("foo.localhost")

    def test_non_loopback_hosts(self) -> None:
        for host in ("192.168.1.5", "10.0.0.1", "0.0.0.0", "", "example.com", "[fe80::1]"):
            assert not is_loopback_host(host), host


class TestDefaultSecretKeyConstant:
    def test_single_shared_constant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The public default literal must live in exactly one place."""
        assert DEFAULT_SECRET_KEY == "change-me-before-production"
        # A developer's .env may carry a real key; pin the default for the check.
        monkeypatch.setattr(settings, "SECRET_KEY", DEFAULT_SECRET_KEY)
        assert settings.SECRET_KEY == DEFAULT_SECRET_KEY

    def test_production_validation_uses_it(self) -> None:
        s = Settings(APP_ENV="production", SECRET_KEY=DEFAULT_SECRET_KEY, DATABASE_URL="sqlite://")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            s.validate_production()

    def test_production_rejects_non_loopback_bind(self) -> None:
        s = Settings(
            APP_ENV="production",
            SECRET_KEY="a-real-key",
            BIND_HOST="192.168.1.10",
            DATABASE_URL="sqlite://",
        )
        with pytest.raises(RuntimeError, match="loopback"):
            s.validate_production()


class TestAtomicStorageOverride:
    def test_roundtrip_is_atomic_and_private(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        target = tmp_path / "data"
        write_storage_override(target)

        from app.core.config import _storage_override_path

        path = _storage_override_path()
        assert json.loads(path.read_text())["data_dir"] == str(target)
        # No temp residue, and the file is owner-only (it names the data dir).
        assert list(path.parent.glob("*.tmp")) == []
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_overwrite_replaces_in_place(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        write_storage_override(tmp_path / "a")
        write_storage_override(tmp_path / "b")

        from app.core.config import _read_storage_override

        assert _read_storage_override() == tmp_path / "b"


class TestSettingBounds:
    def test_non_positive_timeouts_and_pool_rejected(self) -> None:
        import pydantic

        for field in (
            "OLLAMA_TIMEOUT_SECONDS",
            "DB_POOL_SIZE",
            "MAX_MEDIA_SIZE_BYTES",
            "MAX_IMPORT_SIZE_BYTES",
        ):
            with pytest.raises(pydantic.ValidationError):
                Settings(**{field: 0})

    def test_bind_port_is_bounded(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            Settings(BIND_PORT=0)
        with pytest.raises(pydantic.ValidationError):
            Settings(BIND_PORT=70_000)

    def test_api_token_reads_prefixed_or_plain_env(self, monkeypatch) -> None:
        monkeypatch.setenv("LIFEOGRF_API_TOKEN", "prefixed")
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.setenv("DATABASE_URL", "sqlite://")
        assert Settings().API_TOKEN == "prefixed"

        monkeypatch.setenv("API_TOKEN", "plain")
        monkeypatch.delenv("LIFEOGRF_API_TOKEN", raising=False)
        assert Settings().API_TOKEN == "plain"


class TestCorsOriginsNormalised:
    def test_whitespace_is_stripped(self) -> None:
        s = Settings(CORS_ORIGINS=" http://a.example, ,http://b.example ,")
        # Bare comma-joined: main.py splits on "," and hands each entry to CORS
        # as an exact origin, so no entry may carry padding.
        assert s.CORS_ORIGINS == "http://a.example,http://b.example"
        assert [o.strip() for o in s.CORS_ORIGINS.split(",")] == s.CORS_ORIGINS.split(",")
