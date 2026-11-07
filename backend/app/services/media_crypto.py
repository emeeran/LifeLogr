"""Chunked AES-GCM for attachment encryption at rest.

Design and rationale: ``docs/design/media-encryption.md``. The short version:

* One AEAD blob per file would break ``Range`` requests (video/audio seeking) and
  force whole-file decryption into RAM. Instead each 1 MiB chunk is encrypted and
  authenticated independently, with a random 96-bit nonce prefix + chunk index.
* The storage path is bound into the AAD, so a blob copied over another file
  fails authentication rather than decrypting into the wrong entry.
* The key is HKDF-derived from ``SECRET_KEY`` with a **domain-separated** info
  string, so media and credential/token keys never overlap.

Nothing here touches the database or an HTTP route: it is the codec only.
Wiring it into upload/serve/migration is the next task.
"""

from __future__ import annotations

import os
import secrets
import struct
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

MAGIC = b"LLM1"
DEFAULT_CHUNK_SIZE = 1024 * 1024
MIN_CHUNK_SIZE = 64 * 1024
MAX_CHUNK_SIZE = 8 * 1024 * 1024

# magic(4) | chunk_size(4) | nonce_prefix(12) | plaintext_len(8) = 28 bytes
_HEADER = struct.Struct("<4sI12sQ")
_HEADER_SIZE = _HEADER.size
_TAG_SIZE = 16

_KDF_SALT = b"lifelogr-encryption-v2"
_KDF_INFO = b"lifelogr-media-v1"
_AAD_PREFIX = b"lifelogr-media\x00"


def derive_media_key(secret_key: str | bytes) -> bytes:
    """32-byte media key, domain-separated from the credentials key."""
    material = secret_key.encode() if isinstance(secret_key, str) else secret_key
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        info=_KDF_INFO,
    ).derive(material)


@lru_cache(maxsize=1)
def _cached_media_key(secret: str) -> bytes:
    return derive_media_key(secret)


def media_key() -> bytes:
    """The active installation's media key (refuses the shipped default key)."""
    from app.core.security import ensure_custom_secret_key

    ensure_custom_secret_key()
    return _cached_media_key(settings.SECRET_KEY)


def is_encrypted(blob: bytes) -> bool:
    """True when *blob* starts with the encrypted-media magic."""
    return len(blob) >= len(MAGIC) and blob[: len(MAGIC)] == MAGIC


def looks_encrypted(blob: bytes) -> bool:
    """True when *blob* parses as a complete encrypted-media blob.

    Stricter than :func:`is_encrypted` (bare magic): an ordinary upload that
    merely *starts* with the four magic bytes must be treated as plaintext,
    not pushed into a decrypt path that fails forever.
    """
    if not is_encrypted(blob):
        return False
    try:
        _parse_header(blob)
    except ValueError:
        return False
    return True


def _aad(storage_path: str, chunk_index: int) -> bytes:
    return _AAD_PREFIX + storage_path.encode("utf-8") + b"\x00" + chunk_index.to_bytes(4, "little")


def _nonce(prefix: bytes, chunk_index: int) -> bytes:
    return prefix + chunk_index.to_bytes(4, "little")


def _validate_chunk_size(chunk_size: int) -> None:
    if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError(
            f"invalid chunk size {chunk_size} "
            f"(expected {MIN_CHUNK_SIZE}..{MAX_CHUNK_SIZE})"
        )


def _encrypted_size(plaintext_len: int, chunk_size: int) -> int:
    if plaintext_len == 0:
        return _HEADER_SIZE
    full, remainder = divmod(plaintext_len, chunk_size)
    return (
        _HEADER_SIZE
        + full * (chunk_size + _TAG_SIZE)
        + ((remainder + _TAG_SIZE) if remainder else 0)
    )


class _Header:
    __slots__ = ("chunk_size", "nonce_prefix", "plaintext_len")

    def __init__(self, chunk_size: int, nonce_prefix: bytes, plaintext_len: int) -> None:
        self.chunk_size = chunk_size
        self.nonce_prefix = nonce_prefix
        self.plaintext_len = plaintext_len


def _parse_header(blob: bytes) -> _Header:
    if len(blob) < _HEADER_SIZE:
        raise ValueError("truncated encrypted media header")
    magic, chunk_size, nonce_prefix, plaintext_len = _HEADER.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError("not an encrypted media blob")
    _validate_chunk_size(chunk_size)
    expected = _encrypted_size(plaintext_len, chunk_size)
    if len(blob) != expected:
        raise ValueError(
            f"encrypted media size mismatch (got {len(blob)}, expected {expected})"
        )
    return _Header(chunk_size, nonce_prefix, plaintext_len)


def encrypt_media(
    plaintext: bytes,
    storage_path: str,
    *,
    key: bytes | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bytes:
    """Encrypt *plaintext* into the chunked blob described above."""
    _validate_chunk_size(chunk_size)
    aes = AESGCM(key if key is not None else media_key())
    prefix = secrets.token_bytes(12)
    out = bytearray(_HEADER.pack(MAGIC, chunk_size, prefix, len(plaintext)))

    index = 0
    for offset in range(0, len(plaintext), chunk_size):
        chunk = plaintext[offset : offset + chunk_size]
        out += aes.encrypt(_nonce(prefix, index), chunk, _aad(storage_path, index))
        index += 1
    return bytes(out)


def _decrypt_chunk(
    aes: AESGCM,
    blob: bytes,
    header: _Header,
    index: int,
    storage_path: str,
) -> bytes:
    offset = _HEADER_SIZE + index * (header.chunk_size + _TAG_SIZE)
    remaining = header.plaintext_len - index * header.chunk_size
    plain_len = min(header.chunk_size, remaining)
    if plain_len <= 0:
        raise ValueError(f"chunk {index} out of range")
    ciphertext = blob[offset : offset + plain_len + _TAG_SIZE]
    try:
        return aes.decrypt(
            _nonce(header.nonce_prefix, index),
            ciphertext,
            _aad(storage_path, index),
        )
    except InvalidTag as exc:
        raise ValueError(
            f"chunk {index} of {storage_path!r} failed authentication "
            "(wrong key, wrong path, or damaged data)"
        ) from exc


def decrypt_media(
    blob: bytes,
    storage_path: str,
    *,
    key: bytes | None = None,
) -> bytes:
    """Decrypt a whole blob, verifying every chunk."""
    header = _parse_header(blob)
    aes = AESGCM(key if key is not None else media_key())
    out = bytearray()
    index = 0
    while len(out) < header.plaintext_len:
        out += _decrypt_chunk(aes, blob, header, index, storage_path)
        index += 1
    if len(out) != header.plaintext_len:
        raise ValueError("decrypted length does not match the header")
    return bytes(out)


def probe_file(path: str | os.PathLike[str]) -> tuple[bool, int]:
    """``(is_encrypted, plaintext_len)`` from a stored file's first bytes.

    For a plaintext file ``plaintext_len`` is ``0`` (the caller stats the file
    instead). Only the 28-byte header is read — safe on a file of any size.
    The header's size-vs-``plaintext_len`` consistency check is skipped here
    (it would need the whole file); chunk authentication still guards reads.
    A file whose magic matches but whose header fields are nonsense is
    reported as **plaintext** — that is an ordinary upload starting with the
    bytes ``LLM1``, not a blob, and must not be pushed into the decrypt path.
    """
    with open(path, "rb") as f:
        head = f.read(_HEADER_SIZE)
    if not is_encrypted(head):
        return False, 0
    if len(head) < _HEADER_SIZE:
        return False, 0
    _magic, chunk_size, _nonce_prefix, plaintext_len = _HEADER.unpack(head)
    try:
        _validate_chunk_size(chunk_size)
    except ValueError:
        return False, 0
    return True, plaintext_len


def read_range_file(
    path: str | os.PathLike[str],
    storage_path: str,
    start: int,
    length: int,
    *,
    key: bytes | None = None,
) -> bytes:
    """Decrypt ``[start, start+length)`` of an encrypted file **on disk**.

    Seeks straight to the chunks overlapping the range and reads only those,
    so a video seek costs at most two chunk reads instead of the whole file.
    Callers must verify :func:`probe_file` reported an encrypted file first.
    """
    with open(path, "rb") as f:
        head = f.read(_HEADER_SIZE)
        if not is_encrypted(head):
            raise ValueError("not an encrypted media blob")
        magic, chunk_size, nonce_prefix, plaintext_len = _HEADER.unpack(head)
        _validate_chunk_size(chunk_size)
        header = _Header(chunk_size, nonce_prefix, plaintext_len)
        if start < 0 or length < 0 or start + length > header.plaintext_len:
            raise ValueError(
                f"range {start}+{length} exceeds plaintext length {header.plaintext_len}"
            )
        aes = AESGCM(key if key is not None else media_key())
        first = start // header.chunk_size
        last = (start + length - 1) // header.chunk_size
        out = bytearray()
        for index in range(first, last + 1):
            offset = _HEADER_SIZE + index * (header.chunk_size + _TAG_SIZE)
            remaining = header.plaintext_len - index * header.chunk_size
            plain_len = min(header.chunk_size, remaining)
            f.seek(offset)
            ciphertext = f.read(plain_len + _TAG_SIZE)
            try:
                plain = aes.decrypt(
                    _nonce(header.nonce_prefix, index),
                    ciphertext,
                    _aad(storage_path, index),
                )
            except InvalidTag as exc:
                raise ValueError(
                    f"chunk {index} of {storage_path!r} failed authentication "
                    "(wrong key, wrong path, or damaged data)"
                ) from exc
            chunk_start = index * header.chunk_size
            low = max(0, start - chunk_start)
            high = min(len(plain), start + length - chunk_start)
            out += plain[low:high]
    return bytes(out)
