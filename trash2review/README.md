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

Each file's reason for being moved is logged in `.pipeline/purge-plan.md`.

> **Note:** the `backend/`, `docs/`, and `frontend/` items below were parked by
> the 2026-10-27 pipeline run and are still awaiting human review. Items added
> by the 2026-11-08 run are logged separately in that run's purge plan.
