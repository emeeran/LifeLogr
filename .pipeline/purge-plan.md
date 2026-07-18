# Phase 1 — Redundant File Purge (DRY-RUN PLAN)

Generated for branch `cleanup/pipeline-2026-07-18` (off `feature/perf-and-debloat`),
2026-07-18. **Nothing has been moved yet.** This plan is for human review. On `--apply`,
each row is acted on via `git mv` to `trash2review/` (nothing is `rm`'d).

Scan method: content-hash (MD5) dupes over all tracked files; name-pattern sweep
(`_old|_v[0-9]|.bak|.orig| copy |_legacy|_deprecated|~`); committed build/cache artifacts;
reference cross-check via `git grep` + Phase-0 inventory ref-count heuristic, then
manual resolution of every zero-ref candidate (tests excluded — they're run, not imported).

## Headline

The repo is **mostly clean of dead files** — no `*_old.py`, no `*.bak`, no `v1`/`v2`
siblings, no committed `__pycache__`/`node_modules`/`.pyc`. The 2026-07-12 run already
swept the backend; the backend is still clean. This pass surfaces **1 orphan audio
duplicate** and **4 unreferenced frontend components** that the prior run's heuristic
missed. Reported as-is, not padded.

## Actionable (move to `trash2review/` on `--apply`)

| # | path | reason | confidence | inbound-refs | action on --apply |
|---|------|--------|-----------|-------------|-------------------|
| 1 | `media/Garden.mp3` | exact content dup of `frontend/public/Garden.mp3` (the one actually referenced: `memorial.py:36`, `App.vue:74`). `media/` root dir contains only this file; referenced nowhere. | HIGH | 0 | `git mv` → `trash2review/media/Garden.mp3` (memorial audio — confirm) |
| 2 | `frontend/src/components/common/BaseModal.vue` | 0 occurrences anywhere in `frontend/src`; no global registration (`main.ts` registers only Pinia + router), no auto-import plugin. Looks like a reusable-kit component never wired up. | HIGH (confirm intent) | 0 | `git mv` → `trash2review/` |
| 3 | `frontend/src/components/common/EditorButton.vue` | 0 occurrences anywhere. Same as above. | HIGH (confirm intent) | 0 | `git mv` → `trash2review/` |
| 4 | `frontend/src/components/common/StateView.vue` | only self-references (its own doc-comment examples); never actually used. | HIGH (confirm intent) | 0 | `git mv` → `trash2review/` |
| 5 | `frontend/src/components/notes/NoteListItem.vue` | 0 occurrences anywhere. | HIGH (confirm intent) | 0 | `git mv` → `trash2review/` |

> Note on #2–5: these read as a half-wired "common components" kit. They are genuinely
> unreferenced today, so the pipeline defaults to staging them — but if they're meant as
> an intentional library for upcoming work, keep them. `--apply` only acts once you confirm.

## LOW (flagged, not moved)

| path | note |
|------|------|
| `desktop/src-tauri/gen/schemas/capabilities.json` | Tauri-generated; its siblings (`desktop-schema.json`, `linux-schema.json`, `acl-manifests.json`) were already untracked + `.gitignore`'d by the 2026-07-12 run. This one remains tracked. Consider `git rm --cached` + ignore. Left alone here (may be load-bearing for the Tauri build config) — decision deferred to a desktop-build verification. |
| root `media/` dir | After #1 is moved, this dir is empty (git drops it). If `media/` is a runtime data dir, add `media/` to `.gitignore` (only `backend/media/` is ignored today). |

## Already staged by the 2026-07-12 run (pending YOUR keep/delete — not re-moved)

These originals are confirmed absent from the live tree; they await your review, not
another pipeline action:

```
trash2review/frontend/src/stores/analytics.ts
trash2review/frontend/src/assets/tariq-memorial.jpg          (dup of live .../tariq-memorial-tribute.jpg)
trash2review/frontend/src/composables/useAsyncAction.ts
trash2review/frontend/src/components/search/SearchView.vue
trash2review/frontend/src/components/analytics/AnalyticsView.vue
```

## Considered and explicitly KEPT (do not move)

| path(s) | why kept |
|---------|----------|
| 8× empty `__init__.py` (+ empty `.pipeline/baseline-frontend-typecheck.txt`) | Python package markers (the `.txt` is a pipeline artifact — empty means typecheck passed). Not redundancy. |
| `assets/lifelogr-logo.png` vs `frontend/public/logo.png` | exact dupes by hash, **both referenced in distinct roles**: `assets/lifelogr-logo.png` by `backend/app/main.py` + `scripts/build-web-deb.sh`; `public/logo.png` by `Sidebar.vue` + `AboutTab.vue`. |
| `desktop/src-tauri/icons/*` (incl. iOS `AppIcon-*-1.png`) | Tauri/iOS icon sets; asset catalogs reference each variant. Regenerable, platform-required. |
| `frontend/public/Garden.mp3` | the **referenced** copy (the orphan `media/Garden.mp3` is the one moved). |

## After --apply

Re-run `uv run pytest tests/ -q` (backend) + `npm run build` (frontend, catches dead
component imports). If anything breaks, the moved file is restored immediately and logged
here as a false positive.
