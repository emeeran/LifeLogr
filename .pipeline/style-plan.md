# Style Plan — 2026-11-08 (Phase 3 dry run)

Conventions detected as dominant: backend = ruff+mypy gates, hand-wrapped ~88
cols, short one-liner docstrings, raise-based core.exceptions; frontend =
style-free ESLint + extensionless relative imports; desktop = rustfmt defaults.

## Apply — mechanical, zero-risk (batch commit)

| # | Finding | Change |
|---|---|---|
| 1 | OAuth success pages use three different icons (box.py 📦, dropbox.py/onedrive.py ✅, google_drive.py 🎉; error page ❌) | Unify on ✅ — status marker matching the error page, not per-provider mascots |
| 3 | 10 settings-panel/tabs files + tts.ts import `errMsg` with explicit `.ts` extension; the other 24 consumers use extensionless `errorMessage`; the alias is explicitly "legacy" in utils/errorMessage.ts:23 | Switch all 10 to `import { errorMessage }` (extensionless), update references |
| 7 | 17 of ~117 backend test files carry redundant `@pytest.mark.asyncio` while pyproject sets `asyncio_mode = "auto"` | Drop the markers |
| 9 | desktop/src-tauri/src/main.rs fails `cargo fmt --check` (9 hunks, only file in crate) | Run `cargo fmt` |
| 10 | .gitignore:12 `local/ ` trailing space (works today, breaks if "fixed" wrong) | Normalize to `local/` |
| 11 | routers/entries.py:380 imports private `_ENCRYPTED_PLACEHOLDER` from notes_export_service | Promote to public `ENCRYPTED_PLACEHOLDER`, update the one other internal use |

## Apply — needs care (own commit, verify error paths)

| # | Finding | Change |
|---|---|---|
| 2+4 | frontend/src/api/data.ts re-declares BASE_URL and uses raw `fetch` (loses waitForBackend, timeouts, backend `detail` in ApiError); ExportPanel.vue:227 second raw-fetch bypass | Route both through client.ts's `request()`/`blobRequest`; happy path identical, error toasts improve |

## Apply — perf hygiene

| # | Finding | Change |
|---|---|---|
| 5 | LocalFileProvider (cloud_sync_service.py:255-298, dev/testing provider) does blocking file IO on the event loop while the rest of the module wraps syscalls in asyncio.to_thread | Wrap in asyncio.to_thread |

## Leave alone / needs human ruling

- **6 — trash2review tracked files**: that's this pipeline's own holding pen;
  the human empties it later. Not a style defect. (Kept.)
- **8 — services naming split** (`*_service.py` class modules vs bare
  pure-function modules; export_service vs notes_export_service boundary):
  rename would be churn-heavy; document in AUDIT.md instead.
- **12 — RATE_LIMIT knob** (one reader, one value, advertised at main.py:231):
  demoting to a constant breaks env override; needs a human call. Flagged in
  AUDIT.md.
