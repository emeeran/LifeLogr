# Phase 1 — Redundant File Purge (DRY-RUN PLAN)

Generated for branch `debloat`. **Nothing has been moved yet.** This plan is for
human review. On `--apply`, each HIGH/MEDIUM row is acted on; LOW rows are
explicitly left alone and only documented here.

Scan method: content-hash dupes over all tracked files; name-pattern sweep
(`_old|_v[0-9]_copy~|.bak|.orig| copy.|_legacy|_deprecated`); committed
build/cache artifacts; reference cross-check via grep + Phase-0 inventory.

## Headline

The repo is **mostly clean of dead files** — no `*_old.py`, no `*.bak`, no
`v1`/`v2` siblings, no committed `__pycache__`/`node_modules`. Only one true
unreferenced duplicate and one set of regenerable build artifacts turned up.
That is reported as-is, not padded.

## Actionable

| # | path | reason | confidence | inbound-refs | action on --apply |
|---|------|--------|-----------|-------------|-------------------|
| 1 | `frontend/src/assets/tariq-memorial.jpg` | exact content duplicate of `tariq-memorial-tribute.jpg`; the **`-tribute` variant is the one imported** (DedicationTab.vue:9, SplashScreen.vue:11). This file is referenced by nothing. | HIGH | 0 | `git mv` → `trash2review/` (sentimental asset — confirm) |
| 2 | `desktop/src-tauri/gen/schemas/desktop-schema.json` | Tauri-generated build artifact, regenerable, not source | MEDIUM | 0 (consumed at Tauri build time) | `git rm --cached` + add to `.gitignore` |
| 3 | `desktop/src-tauri/gen/schemas/linux-schema.json` | identical to desktop-schema.json; Tauri-generated | MEDIUM | 0 | `git rm --cached` + `.gitignore` |
| 4 | `desktop/src-tauri/gen/schemas/acl-manifests.json` | Tauri-generated capability manifest | MEDIUM | 0 | `git rm --cached` + `.gitignore` (**verify desktop build still works** — project ships web-deb, so low blast radius) |

**Caveat on #2–4:** the pipeline allows untracking regenerable build artifacts
instead of `trash2review`. Tauri *can* regenerate these on `tauri build`/`tauri
icon`. If you actively build the desktop app on a machine without regenerating,
untracking is mildly disruptive — hence MEDIUM, not HIGH. Recommend confirming
a desktop build still green-lights before applying.

## Considered and explicitly KEPT (do not move)

| path | why kept |
|------|----------|
| `frontend/public/logo.png` vs `assets/lifelogr-logo.png` | exact dupes by hash, **but both referenced** — `/logo.png` in AboutTab/Sidebar; `assets/lifelogr-logo.png` served by backend main.py:347 + packaged by build-web-deb.sh. Different roles. |
| `desktop/src-tauri/icons/ios/AppIcon-*@*-1.png` | exact dupes of the non-`-1` siblings, but iOS asset catalogs reference them via `Contents.json`; removing risks the iOS icon set. Secondary platform (web-deb is primary). |
| `backend/app/**/__init__.py` (empty) | Python package markers, not redundancy. |
| `backend/scripts/export_conv.py` | no importer (grep), but it's a standalone CLI script — entry points aren't expected to be imported. Flag for human: still wanted? |
| `backend/app/routers/ai.py`, `schemas/ai.py` | flagged as zero-ref by the heuristic only because the token `ai` is <3 chars; actually registered in main.py:248 (`include_router(ai_router)`). Live. |
| all `tests/**` & `docs/**` | zero inbound refs expected — tests are run not imported; docs are standalone. Not orphans. |

## After --apply

Re-run `uv run pytest tests/ -q` + `npm run build`. If anything breaks, the
moved file is restored immediately and logged here as a false positive.
