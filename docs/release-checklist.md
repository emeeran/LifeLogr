# Release Checklist — LifeLogr

Run through this before tagging a release. It catches the failures that CI can't
(end-to-end data round-trips) and the drift CI only flags after the fact.

## 1. Version sources agree
```bash
make check-version
```
All four version files (`backend/pyproject.toml`, `backend/app/core/config.py`,
`desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/tauri.conf.json`) must match.
If not, `make bump V=x.y.z` and re-run.

## 2. Quality gates green (the CI bars)
```bash
make lint            # ruff + mypy (strict)
make test            # backend pytest (coverage gate ≥ 62%)
cd frontend && npx vue-tsc -b && npm run build
cd desktop/src-tauri && cargo check
```
All must pass. The backend suite uses isolated temp DBs — it must NOT touch your
real journal data.

## 3. Encryption round-trip (no entry may become undecryptable)
- Encrypt an entry + a note with a known passphrase.
- Restart the app.
- Decrypt both — they must restore the original body.
- This guards the KDF version chain (scrypt `v2:` → PBKDF2 modern → PBKDF2
  legacy deterministic-salt). A regression here is catastrophic.

## 4. Backup → restore round-trip (the data-loss surface)
- Create entries with media. Run a **local** backup (`Settings → Data → Back up now`).
- Import the archive into a **fresh data dir** (`Settings → Data → Storage location`
  → point at an empty dir, then import).
- Confirm entries + media survived.
- If a cloud provider is configured, repeat via the **cloud restore** path
  (`BackupService.restore()`): download → extract → atomic_restore.

## 5. Cloud-sync providers (if shipping changes to `cloud_sync_service`)
- Each configured provider (Google Drive / OneDrive / Dropbox / Box / WebDAV):
  run a backup, then list snapshots, then restore the latest.
- The token-refresh callback must persist rotated credentials (Box rotates its
  refresh token every refresh).

## 6. Schema migration parity
- On a DB from the previous release, start the app and confirm
  `PRAGMA user_version` (FTS rebuild) + `_schema_meta.schema_version` advance to
  the current target without errors, and entries are intact.

## 7. Desktop smoke (the sidecar lifecycle)
- Launch, use the app, **fully quit** (not just close the window).
- Confirm no `lifelogr-backend` process remains and port 18765 is free
  (`shutdown_sidecar` killed the exact child PID).
- Relaunch — `reclaim_port` should find the port free.

## 8. Tag & build
- `git tag vX.Y.Z` → triggers Build & Release (Linux deb/AppImage, Windows MSI,
  macOS DMG). The macOS build targets x86_64 (`macos-13`) so it runs on Intel
  natively and Apple Silicon via Rosetta.
- Install the artifact on a clean machine and run steps 3–4 against a brand-new
  data dir.
