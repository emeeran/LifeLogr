# Phase 1 Purge Plan — dry run (2026-10-27)

Method: exact-hash dedup across all 541 tracked files, name/artifact pattern scan,
and a full inbound-reference sweep (git grep per candidate, excluding generated dirs).

## Purge candidates (git mv → trash2review/)

| path | reason | confidence | inbound refs |
|---|---|---|---|
| `frontend/public/icons.svg` | unreferenced SVG sprite in public/ | high | 0 |
| `docs/images/lifelogr_aboutus.jpg` | unreferenced screenshot (README links only lifelogr_01.jpg + lifelogr_Editor.jpg) | high | 0 |
| `docs/blog_lifelogr_vs_diarium.md` | unreferenced blog draft; not part of manual, not linked anywhere | high | 0 |

## Already deleted by human (fold into phase 1 commit, not git mv)

16 tracked docs/ files deleted in the working tree at human direction
(ADR 001–006, BUILD_GUIDE, audit-2026-10-18, data-management ×2,
diarium-enhancement ×2, diarium-format-analysis, release-checklist, roadmap).
Committed separately as their own commit so pipeline history stays clean.

## Reviewed and kept (do NOT purge)

- `assets/lifelogr-logo.png` ≡ `frontend/public/logo.png` — same bytes, but two
  independent consumers (backend deb packaging, frontend public dir). Keep both.
- Tauri iOS icon `@2x-1` duplicates — required by Apple icon naming convention.
- Empty `__init__.py` files — Python package markers.
- `backend/.env.example` — referenced by ARCHITECTURE.md; conventional file.
- `docs/data-management-overhaul-plan.md` / `-tasks.md` and `docs/diarium-enhancement-*`
  — companion planning docs, recent commits, deliberate pairs (NOTE: human deleted
  these during the session; no action needed from this plan).
- ADRs 001/003/006 unreferenced — ADRs are historical records by convention.
- `.pipeline/*` — pipeline's own artifacts, required by this run.
