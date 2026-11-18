# Design — encrypting media at rest

**Status:** proposed (2026-11-07) · **Scope:** SEC-MEDIA / SEC-KEYS in
`docs/plans/2026-11-07-modify-idea-tasks.md` (archived in trash2review/) · **Decision:** approved (DEC-3).

## 1. Why

Entry and note **text** can be encrypted per item (`Entry.is_encrypted`,
`Note.is_encrypted`), but attachments are not: a photo attached to an encrypted
journal entry is a plaintext, fully decodable file in `MEDIA_DIR` — and in every
backup and cloud copy. Thumbnails are worse: `MediaService._write_thumbnail`
caches a **plaintext WebP** of every image under `DATA_DIR/thumbs`, regardless of
the parent's encryption. A user who encrypted a sensitive entry still leaks its
images.

The goal is: **when an item is encrypted, its attachments and thumbnails are
unreadable on disk and in backups.** Plaintext media for unencrypted items stays
as it is (fast, seekable, no behaviour change).

## 2. Key hierarchy (existing, reused)

`core/security.py` already derives the credentials key from `SECRET_KEY` with
HKDF-SHA256 (`salt="lifelogr-encryption-v2"`, `info="aes-256-gcm-key"`). Media
reuses the root with **domain separation** so the two key spaces never overlap:

```
SECRET_KEY
 ├─ HKDF(info="aes-256-gcm-key")         → credentials / (future) text key
 └─ HKDF(info="lifelogr-media-v1")       → media key (32 bytes)
```

No new secret: a packaged install already generates `.secret_key`; a dev checkout
uses `SECRET_KEY`. `ensure_custom_secret_key()` is called before any media
encryption so the public default key can never silently "encrypt" attachments.

**Consequence:** losing `SECRET_KEY` loses media too. That is why the recovery kit
(§8) is part of this wave, not an optional extra.

## 3. Blob format — chunked AEAD (v1)

A single AES-GCM blob per file would make `Range` requests impossible (media
elements and video playback use them) and force whole-file decryption into RAM.
Use an independently-authenticated **chunk** format instead:

```
header (28 bytes)
  "LLM1"          4   magic + version
  chunk_size      4   uint32, little-endian (default 1 MiB)
  nonce_prefix   12   random per file
  plaintext_len   8   uint64, little-endian
then ceil(len/chunk_size) records:
  ciphertext||tag  chunk_size + 16 (last chunk may be shorter)
```

- Per-chunk nonce = `nonce_prefix || uint32_le(chunk_index)` — unique per
  (file, chunk) with a random 96-bit prefix; no nonce reuse across files.
- **AAD** = `b"lifelogr-media\x00" + storage_path + b"\x00" + chunk_index_le`.
  Binding the path means a blob copied over another file fails authentication
  instead of decrypting into the wrong entry.
- Authentication is per chunk, so a `Range` request decrypts only the chunks it
  overlaps; a corrupted chunk fails loudly at that chunk and nowhere else.
- Everything is validated before use: chunk_size ∈ [64 KiB, 8 MiB], plaintext_len
  consistent with the file size, path is the expected storage path.

`Range` mapping: `start_byte` → `chunk = start // chunk_size`, `offset = start %
chunk_size`; serve the decrypted plaintext slice(s) with a `206` and the standard
`Content-Range`. Decrypting at most two chunks per request keeps memory flat.

## 4. Detection — magic sniffing, no schema change

`MediaService` reads the first 4 bytes: `LLM1` ⇒ encrypted, else plaintext. This
avoids a migration and keeps working for orphaned files (media whose row is gone).
Thumbnails are **not** magic-sniffed (they are always WebP); an encrypted
thumbnail uses a `.llm1` sibling name (`<hash>.webp.llm1`) so the two coexist.

## 5. Encryption policy

| Parent | New uploads | Existing media | Thumbnails |
|---|---|---|---|
| Encrypted entry/note | encrypt | encrypted by the maintenance job (opt-in, dry-run first) | encrypted cache |
| Plaintext item | plaintext (unchanged) | untouched | plaintext cache |

A setting `encrypt_media` (default **on** for encrypted parents after rollout;
initially off at the maintenance-job level) gates the *migration* of existing
files, not the policy for new uploads. When an item is decrypted, its media is
**not** decrypted automatically — decrypting the text while leaving the photo
encrypted is safe; the reverse is not.

## 6. Serving and failure modes

- `/media/{id}/file` and `/thumb` decrypt through the same chunked reader; both
  are async endpoints that offload to a thread.
- Any authentication failure (wrong key, tampering, path mismatch) returns **409
  "Attachment cannot be decrypted with this installation's key"** and logs the
  storage path. Never delete or overwrite on a decrypt failure.
- The list/timeline endpoints stay metadata-only (they already are), so an
  encrypted gallery does not decrypt anything until a thumbnail is requested.
- OCR: decrypts to memory for Tesseract; it must not write a plaintext temp file
  (verify `ocr_service` does not).

## 7. Migration of existing media

A maintenance action "Encrypt attachments of encrypted items":

1. Dry run: count encrypted parents with plaintext media (and their bytes).
2. Apply: for each file — read, chunk-encrypt, write `.tmp`, fsync, `replace`,
   delete the plaintext thumbnail (a stale plaintext WebP must not survive).
3. Resumable: a file already starting with `LLM1` is skipped; reruns are safe.
4. Never touches plaintext items. Never deletes the only copy: on any write
   failure, keep the original and report the path.

## 8. Recovery kit (SEC-KEYS)

Losing `SECRET_KEY` already loses cloud credentials; after this change it also
loses attachments, so a recovery path becomes mandatory.

- **Export:** `scrypt(passphrase, salt, n=2^15, r=8, p=1)` → 32-byte KEK →
  AES-256-GCM over the current `SECRET_KEY`, AAD `"lifelogr-recovery-kit-v1"`.
  File `lifelogr-recovery.json`:
  `{format:1, kdf:{name:"scrypt",n,r,p,salt}, nonce, ciphertext, created_at, app_version}`.
- **Recovery code:** 24 base32 characters (120 bits) shown for printing and
  accepted as an alternative to the passphrase: the code *is* the passphrase
  input to the same KDF. (Deviation from the plan's "24 words": no wordlist
  dependency and no transcription ambiguity; base32 is unambiguous when grouped
  `XXXX-XXXX-…`.)
- **Import:** unwrap, probe-decrypt one credential and one media chunk, then
  persist; refuse to overwrite a different existing key without an explicit
  confirmation.
- **Warning:** encrypted users without a kit see a one-time banner on the
  Encryption settings section.

## 9. Backups

Encrypted blobs travel as ciphertext inside the archive; the manifest hashes
ciphertext (§ manifest = a checksum, not a confidentiality boundary). Restoring
on an installation with a different `SECRET_KEY` restores files that cannot be
decrypted — that is correct and must be surfaced: after a restore, the integrity
check should verify that a sample encrypted blob authenticates with the current
key and warn (not fail) if it does not.

## 10. Performance and limits

AES-GCM runs at hundreds of MB/s; the 1 MiB chunk size keeps the working set
small. Encrypted media cannot use `FileResponse`'s zero-copy path, so it is
served through the chunk reader (one or two chunks per Range). Thumbnails are
small. Large videos are the only real cost; measured in the test plan.

## 11. Rollout

1. Land the chunked reader/writer + tests behind `ENCRYPT_MEDIA` (default off).
2. Encrypt on upload for new media of encrypted items.
3. Maintenance dry-run, then migration on a copy, then the real run.
4. Recovery kit before declaring media encryption "on".
5. Docs: `SECURITY.md` (what is and is not encrypted), `USER_MANUAL.md`,
   `ARCHITECTURE.md`.

## 12. Test plan

- Round-trip: 1 byte, exactly chunk_size, chunk_size ± 1, 10 MB random — byte
  equality and Range slices at every boundary.
- Tamper: flip a ciphertext byte → that chunk fails, others still decode; swap
  two files' blobs → AAD path mismatch fails.
- Wrong key → 409, file untouched.
- Thumbnail: encrypted parent produces no plaintext WebP on disk; deleting the
  cache and re-requesting regenerates an encrypted one.
- Migration: dry-run counts, idempotent rerun, failure leaves the original.
- Recovery kit: export → wipe `.secret_key` → import → credential and media
  probes succeed; wrong passphrase and wrong code both fail cleanly.
- Restore: archive with ciphertext restores; sample probe warns under a
  different key.

## 13. Open questions

1. Decrypting an item: leave its media encrypted (planned) or offer "decrypt
   attachments too"? The latter needs a confirmation because it is destructive.
2. Videos over, say, 2 GB: chunked AEAD is fine, but should the UI refuse
   encryption for files above a configurable size instead of paying the decrypt
   cost on every seek?
3. Whether text encryption should also move to the media key (currently the text
   key is the credentials key; not required for this change, but worth aligning
   when there is a version migration).
