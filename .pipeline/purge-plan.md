# Purge Plan — 2026-11-08 (second pipeline pass)

Dry run. Nothing has been moved yet. On approval, each path is `git mv`'d into
`trash2review/<same-relative-path>` and the test suite is re-run.

| path | reason | confidence | inbound-refs-found |
|---|---|---|---|
| `backend/app/schemas/sync.py` | Orphaned module — leftover fallout from the 2026-10-27 run's own `sync.py` router removal. All six symbols (`SyncQueueRequest`, `SyncQueueResponse`, `SyncStatusResponse`, `SyncFlushResponse`, `CloudSyncRequest`, `CloudSyncResponse`) have zero references outside the file itself (verified by grep over `backend/app` + `backend/tests`). The previous run missed it because its basename grep collided with the live `models/sync.py`. | high | none (all six symbols checked) |

## Cleared — explicitly checked and NOT flagged

- No exact/near-duplicate files (md5 sweep over 588 tracked files; duplicate
  groups were adjudicated by the previous run: logo ×2 has two consumers, Tauri
  icon pairs are platform-required).
- No orphaned backend modules beyond the above (24 routers, 30+ services, 18
  models, 17 schemas all referenced; `models/prompt.py` and
  `models/reflection_prompt.py` are distinct live models, not supersessions).
- No orphaned frontend components/composables/utils (basename-reference sweep,
  excluding own tests).
- No superseded generations (`test_archive_v2.py` is a distinct feature test;
  the two `test_notes.py` files are integration vs unit with disjoint coverage).
- No committed build/cache artifacts (`__pycache__`, `.pyc`, `dist/`, logs —
  zero tracked; `.gitignore` coverage confirmed adequate).
- `trash2review/` items from the 2026-10-27 run are out of scope and untouched.

## Noted, no action

- `assets/.genoffice-assets.json` (untracked) — empty genoffice manifest, 70
  bytes, vestigial. Human said leave it; left untouched.
- `.gitignore` line 11: trailing space in `local/ ` pattern (cosmetic; git
  still honors it). Will be normalized during the Phase 3 style pass.
