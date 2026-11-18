# LifeLogr — what is and is not encrypted

Companion to `docs/design/media-encryption.md` (design detail) and
`AUDIT.md` (threat-model notes). This is the user-facing summary.

## Key hierarchy

Everything derives from one root key, `SECRET_KEY`:

```
SECRET_KEY
 ├─ HKDF(info="aes-256-gcm-key")    → cloud-credential key (tokens at rest)
 ├─ HKDF(info="lifelogr-media-v1")  → media key (attachments at rest)
 └─ wrapped by the recovery kit     → scrypt(passphrase) → AES-GCM(SECRET_KEY)
```

A packaged install generates `.secret_key` in the data directory
automatically (mode 0600 — the desktop/web launchers and the app's own
managed-run path both do this); dev/server deployments must set `SECRET_KEY`
themselves. For non-loopback deployments an optional bearer-token gate exists:
set `API_TOKEN` and every `/api/*` call must carry
`Authorization: Bearer …`.

## What is encrypted

| Data | How | Since |
|---|---|---|
| Entry/note **text** (opt-in per item) | passphrase-based per entry — the app cannot read it without your passphrase | before this wave |
| Stored **cloud credentials** (tokens) | AES-256-GCM under the credentials key | before this wave |
| **Attachments of encrypted items** (opt-in via `ENCRYPT_MEDIA`) | chunked AES-256-GCM per file; the storage path is bound in as AAD, so a blob copied to another file fails authentication instead of decrypting | this wave |
| **Thumbnails of encrypted items** | encrypted `.webp.llm1` cache entries; served as decrypted bytes | this wave |
| **Backups** of encrypted items | bodies passphrase-encrypted (unchanged); media travels as ciphertext | this wave |

## What is not encrypted

- Attachments of **plaintext** entries/notes (by design — fast and seekable).
- The SQLite **database file** itself: titles, dates, tags, media metadata and
  search indexes are readable. Only encrypted items' bodies/moods are
  ciphertext inside it.
- Media **filenames** and sizes (metadata columns).
- The `SECRET_KEY` file (`.secret_key`) — it is the root; protect it with file
  permissions and, ideally, disk encryption.

## Database integrity (not encryption, but loss protection)

Boot safety is layered: a fast `PRAGMA quick_check` runs at boot (escalating
to a full `integrity_check` on failure, plus a weekly full check on Sundays
04:00), and rotating `lifelogr.db.boot-bak-*` snapshots (2 recent + weekly)
are kept so a corrupt database is automatically restored from the newest
intact snapshot.

## Failure mode

Any attachment that fails authentication (wrong key, tampering, blob copied
over another path) is served as **HTTP 409** and never deleted or overwritten.

## Recovery kit (Settings → Data → Security)

Losing `SECRET_KEY` loses stored cloud credentials and, with media encryption
on, all encrypted attachments. Export a recovery kit to wrap the key under a
passphrase (or a generated 24-character recovery code):

- the kit file (`lifelogr-recovery.json`) is scrypt-wrapped — it is as
  sensitive as the key itself, keep it somewhere safe;
- importing verifies the key against one stored credential and one encrypted
  media chunk before installing it, and refuses a key that cannot read your
  data;
- replacing an active non-default key always asks for confirmation.

The settings UI warns while encryption is in use and no kit has ever been
exported.

## Threat model (summary)

Local-first, single-user, backend bound to `127.0.0.1`. The encryption here
protects **data at rest** — against disk theft, backup leaks, cloud-provider
inspection, and other people with access to your files. It does not protect
against other processes running as your user while the app is unlocked. The
loopback API is unauthenticated by default (an optional `API_TOKEN` bearer
gate exists for non-loopback deployments, and a `Host`-header guard rejects
DNS-rebinding attempts) — see `AUDIT.md`.
