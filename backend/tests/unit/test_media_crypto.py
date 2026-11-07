"""Codec tests for chunked media encryption (design note §12, first half).

These are pure unit tests — no database, no media directory, no HTTP route.
"""

from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core.config import DEFAULT_SECRET_KEY, settings
from app.core.security import DefaultSecretKeyError
from app.services.media_crypto import (
    MIN_CHUNK_SIZE,
    _HEADER_SIZE,
    _TAG_SIZE,
    decrypt_media,
    derive_media_key,
    encrypt_media,
    is_encrypted,
    looks_encrypted,
    media_key,
    probe_file,
    read_range_file,
)

KEY = b"\x11" * 32
OTHER_KEY = b"\x22" * 32
PATH = "media/images/a.jpg"
CHUNK = MIN_CHUNK_SIZE


def _roundtrip(size: int) -> None:
    data = os.urandom(size)
    blob = encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK)
    assert blob[:4] == b"LLM1"
    assert is_encrypted(blob)
    assert decrypt_media(blob, PATH, key=KEY) == data


@pytest.mark.parametrize(
    "size", [0, 1, 7, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK + 123]
)
def test_roundtrip_at_every_boundary(size: int) -> None:
    _roundtrip(size)


def test_ciphertext_is_not_plaintext_and_nonce_is_random() -> None:
    data = b"a" * 4096
    first = encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK)
    second = encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK)
    assert data not in first
    assert first != second  # random nonce prefix per file


def test_range_reads_match_the_plaintext(tmp_path) -> None:
    data = bytes(range(256)) * (CHUNK // 128)  # 2 chunks exactly
    path = tmp_path / "blob"
    path.write_bytes(encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK))

    assert read_range_file(path, PATH, 0, 10, key=KEY) == data[:10]
    assert read_range_file(path, PATH, CHUNK - 5, 10, key=KEY) == data[CHUNK - 5 : CHUNK + 5]
    assert read_range_file(path, PATH, len(data) - 3, 3, key=KEY) == data[-3:]
    assert read_range_file(path, PATH, 0, len(data), key=KEY) == data
    assert read_range_file(path, PATH, 5, 0, key=KEY) == b""


def test_range_out_of_bounds_is_rejected(tmp_path) -> None:
    path = tmp_path / "blob"
    path.write_bytes(encrypt_media(b"abc", PATH, key=KEY, chunk_size=CHUNK))
    with pytest.raises(ValueError, match="exceeds plaintext length"):
        read_range_file(path, PATH, 2, 5, key=KEY)
    with pytest.raises(ValueError, match="exceeds plaintext length"):
        read_range_file(path, PATH, -1, 1, key=KEY)


def test_tampering_names_the_chunk() -> None:
    data = os.urandom(CHUNK * 2)
    blob = bytearray(encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK))

    first = bytearray(blob)
    first[_HEADER_SIZE + 5] ^= 0x01
    with pytest.raises(ValueError, match="chunk 0"):
        decrypt_media(bytes(first), PATH, key=KEY)

    second = bytearray(blob)
    second[_HEADER_SIZE + CHUNK + _TAG_SIZE + 3] ^= 0x01
    with pytest.raises(ValueError, match="chunk 1"):
        decrypt_media(bytes(second), PATH, key=KEY)


def test_a_blob_copied_to_another_path_fails_authentication() -> None:
    blob = encrypt_media(b"secret", PATH, key=KEY, chunk_size=CHUNK)
    with pytest.raises(ValueError, match="failed authentication"):
        decrypt_media(blob, "media/images/b.jpg", key=KEY)


def test_wrong_key_fails_authentication() -> None:
    blob = encrypt_media(b"secret", PATH, key=KEY, chunk_size=CHUNK)
    with pytest.raises(ValueError, match="failed authentication"):
        decrypt_media(blob, PATH, key=OTHER_KEY)


def test_header_validation() -> None:
    blob = encrypt_media(b"abc", PATH, key=KEY, chunk_size=CHUNK)

    with pytest.raises(ValueError, match="not an encrypted media blob"):
        decrypt_media(b"XXXX" + blob[4:], PATH, key=KEY)
    with pytest.raises(ValueError, match="truncated"):
        decrypt_media(blob[:10], PATH, key=KEY)
    with pytest.raises(ValueError, match="size mismatch"):
        decrypt_media(blob[:-1], PATH, key=KEY)
    with pytest.raises(ValueError, match="invalid chunk size"):
        encrypt_media(b"abc", PATH, key=KEY, chunk_size=1024)


def test_plaintext_is_not_mistaken_for_ciphertext() -> None:
    assert is_encrypted(b"") is False
    assert is_encrypted(b"\xff\xd8\xff\xe0plain-jpeg") is False
    assert is_encrypted(b"LLM") is False


def test_magic_collision_is_treated_as_plaintext(tmp_path) -> None:
    """An ordinary upload that starts with the magic bytes is not a blob."""
    impostor = tmp_path / "impostor"
    impostor.write_bytes(b"LLM1" + b"\xff" * 24 + b"user text pretending")
    assert is_encrypted(impostor.read_bytes()) is True  # bare magic matches…
    assert looks_encrypted(impostor.read_bytes()) is False  # …but no valid header
    assert probe_file(impostor) == (False, 0)  # so the probe reports plaintext


def test_media_key_derivation_is_deterministic_and_domain_separated() -> None:
    a = derive_media_key("secret-one")
    assert a == derive_media_key("secret-one")
    assert len(a) == 32
    assert a != derive_media_key("secret-two")


def test_media_key_refuses_the_shipped_default_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", DEFAULT_SECRET_KEY)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(DefaultSecretKeyError):
        media_key()


def test_invalid_tag_is_wrapped_as_value_error() -> None:
    """The public codec never leaks cryptography's InvalidTag to callers."""
    blob = encrypt_media(b"x", PATH, key=KEY, chunk_size=CHUNK)
    tampered = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(ValueError) as excinfo:
        decrypt_media(tampered, PATH, key=KEY)
    assert not isinstance(excinfo.value, InvalidTag)


def test_probe_and_read_range_file(tmp_path) -> None:
    """On-disk probe reads only the header; reads decrypt the requested range."""
    import os

    data = os.urandom(CHUNK * 2 + 77)
    path = tmp_path / "blob"
    path.write_bytes(encrypt_media(data, PATH, key=KEY, chunk_size=CHUNK))

    encrypted, plain_len = probe_file(path)
    assert encrypted is True
    assert plain_len == len(data)
    assert read_range_file(path, PATH, 0, len(data), key=KEY) == data
    assert read_range_file(path, PATH, CHUNK - 1, CHUNK + 2, key=KEY) == data[
        CHUNK - 1 : CHUNK * 2 + 1
    ]

    # AAD still binds the on-disk reader to the storage path.
    with pytest.raises(ValueError, match="failed authentication"):
        read_range_file(path, "other/path", 0, 4, key=KEY)


def test_probe_file_rejects_plaintext_and_bad_header(tmp_path) -> None:
    plaintext = tmp_path / "plain"
    plaintext.write_bytes(b"\x89PNG not encrypted")
    assert probe_file(plaintext) == (False, 0)

    blob = tmp_path / "blob"
    blob.write_bytes(encrypt_media(b"abc", PATH, key=KEY, chunk_size=CHUNK)[:-4])
    # The probe skips the header's size-consistency check (it would need the
    # whole file); the missing tag bytes fail authentication at read time.
    encrypted, _ = probe_file(blob)
    assert encrypted is True
    with pytest.raises(ValueError, match="failed authentication"):
        read_range_file(blob, PATH, 0, 3, key=KEY)
