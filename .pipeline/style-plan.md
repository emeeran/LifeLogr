# Phase 3 Style Plan — dry run (2026-10-27)

Convention detection: backend standard is `ruff check` + mypy strict (`make lint`);
frontend is eslint + vue-tsc (`make fe-lint` / `fe-typecheck`). Docstring style is
prose-with-reST-cross-references (`:class:`, `:func:`) uniformly; error philosophy is
raise domain exceptions (`core/exceptions.py`) + wide-catch-with-logged-context at
boundaries — already consistent. No formatter (black/prettier/ruff format) is wired
into the project's workflow.

## Apply

| # | inconsistency | files | resolution |
|---|---------------|-------|------------|
| 1 | Emoji in one toast vs plain house style everywhere else (`'Saved'`, `'Event inserted into entry'`) | `frontend/src/components/entry/EntryEditor.vue:587` | `'Daily goal reached 🎉'` → `'Daily goal reached'` |
| 2 | Stale comment: "Connection pool (for production PostgreSQL)" — the app is SQLite-only and `database.py` uses these knobs for its SQLite QueuePool; `startup_checks.py` even enforces `DB_POOL_SIZE > 1` | `backend/app/core/config.py:345` | fix the comment, no code change |
| 3 | 7 eslint-auto-fixable template-formatting warnings (multiline element content, quote style) clustered in 2 files | `StoragePanel.vue`, `AboutTab.vue` | `eslint --fix`, then vitest |

## Explicitly not applied (and why)

- **`ruff format` across the backend** — it would rewrite 88 of 98 files, but the
  codebase is *uniformly* hand-wrapped to `ruff check`'s rules and `make lint` has no
  format step. Uniform ≠ formatter-generated; running it would impose a new
  convention, not erase a seam. Declined.
- **7 `vue/no-v-html` warnings** — all in markdown renderers (entry/note bodies,
  About tab release notes, search palette). Deliberate feature; sanitization gets
  verified in the Phase 4 security audit instead.
- **5 `vue/require-default-prop` warnings** — optional props on shared settings
  components (`SButton`, `AccordionItem`, `EditorContextMenu`). Adding defaults
  churns component APIs for warnings the project's own `fe-lint` gate already
  tolerates. Left.
- **1 `vue/no-template-shadow` (`Component` in AppShell.vue)** — cosmetic; left to
  avoid touching layout code for a warning the lint gate passes with.
- **OAuth success/error pages' emoji (`✅`/`🎉`/`📦`/`❌`)** — a deliberate parameter
  of the shared styled callback template (`_oauth_helpers.success_page(title, emoji,
  message)`), consistent across all five providers. This is the page's design, not
  AI voice. Kept.
- **`EmojiPicker.vue` emoji data** — the emoji *is* the feature. Kept.
