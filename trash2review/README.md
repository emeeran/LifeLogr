# trash2review/

**This is a holding pen, not a deletion.** Files moved here by the cleanup
pipeline (Phases 1–3) are staged for your review. Nothing has been deleted.

## Why a file lands here

It was judged redundant or dead — a duplicate, an orphan with no inbound
references, a superseded generation, or stale scaffolding — but the pipeline
never `rm`s anything. You get the final call.

## How to restore a file

Files keep their relative path, mirrored under `trash2review/`. To put one back:

```sh
git mv trash2review/<mirrored/path> <original/path>
```

For example, if `backend/app/services/old_thing.py` was moved here:

```sh
git mv trash2review/backend/app/services/old_thing.py backend/app/services/old_thing.py
```

Then re-run the test suite to confirm nothing depended on it.

## When you're done reviewing

Once you've restored anything you want to keep, the rest can be deleted:

```sh
git rm -r trash2review
```

Only do this after you've verified the app still builds and tests pass without
the staged files.
