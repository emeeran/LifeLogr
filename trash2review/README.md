# trash2review — holding pen, not a deletion

Files moved here by the cleanup pipeline were judged redundant or dead, but
**nothing is hard-deleted**. Everything here is still in git history and in the
working tree, just relocated. The human reviews this folder and empties it
(git rm) or restores files individually:

```bash
# restore a file to its original location
git mv trash2review/<original/relative/path> <original/relative/path>

# permanently remove (only after review)
git rm -r trash2review
```

Each run's reasons are logged in its purge plan (in git history, since
`.pipeline/` is no longer tracked):

- **2026-10-27 run** — `backend/`, `docs/`, `frontend/` items (dead sync
  router/schemas, unused tests, unused icons.svg, a blog draft). Still
  awaiting review.
- **2026-11-09 run** — finished planning artifacts (`docs/modify-idea.md`,
  the 2026-11-07 modify-idea plan/tasks pair, `docs/diarium-sync-research.md`,
  their screenshot + genoffice manifests), `scripts/build.sh` (third,
  divergent desktop build path — shipped version 'unknown' and advertised
  windows/mac targets), and the iOS/Android/Windows icon sets
  (`desktop/src-tauri/icons/` AppIcon-*/Square*/StoreLogo/android/ios/
  icon.icns/icon.ico) plus `assets/.genoffice-assets.json`. The app ships
  Linux-only; the removed CI jobs/msi/dmg targets live in git history, not
  here.
