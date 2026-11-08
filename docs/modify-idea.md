# LifeLogr Modifications-Idea

&nbsp;

- [x] Use distinct colors for the Notes tab to improve visual identification,
- [x] Allow pasted images to be resized in both notes and journals
- [x] Move the floating microphone in the journal to be next to the speaker at the bottom
- [x] Ensure data safety and security
- [x] Fix sniper fail in Notes![image](assets/image.png)
- [x] Notes should be draggable, droppable, and nestable
- [x] Auto-title from first line
- [x] Frequently screen goes blank, fix it
- [x] when app closed, it takes some time to close

&nbsp;

---

All nine items are implemented and covered by the automated gate (pytest 1004 ·
vitest 322 · vue-tsc · eslint · Playwright e2e 13/13, verified 2026-11-08).
Task IDs, per-item breakdowns and the plan live in
`docs/plans/2026-11-07-modify-idea-{tasks,plan}.md`.

Item ↔ wave map:

| # | Item | Wave / IDs | Notes |
|---|------|-----------|-------|
| 1 | Note/notebook colours | COL-1…6 | 8 colour tokens, rail stripes/dots, editor popover |
| 2 | Resizable pasted images | RESIZE-2…7 | grip + chip + keyboard resize in both editors; e2e RESIZE-7 |
| 3 | Mic next to speaker | MIC-1…5 | bottom toolbar dock; recording pill popover |
| 4 | Data safety & security | SEC-MEDIA / BACKUP / KEYS / AUDIT | media encryption at rest, manifest+verify, recovery kit |
| 5 | Snip fail (Wayland toast) | CAP-1…7 | portal screenshot + fallback chain; `scripts/snip-smoke.sh` |
| 6 | Notes drag/drop/nest | DND-1…8 | incl. between-row reorder (`notes.sort_order`), cycle guard |
| 7 | Auto-title from first line | TITLE-1…7 | both editors + Settings toggle + maintenance backfill |
| 8 | Blank screen | BLANK-1…8 + route-transition fix | ErrorBoundary, error reporting, thumbs, **`mode="out-in"` + lazy routes fix (BLANK-9 e2e)** |
| 9 | Slow app close | CLOSE-1…5, 7 | bounded teardown, exit guard, PID-precise kill |

Remaining manual (real-GUI) acceptance checks are tracked in
`docs/plans/pending-tasks.md`: MIC-6 width pass, CLOSE-6 close timings,
the strings-on-media encryption check, the Wave-3 move-10-notes pass, and
the snip smoke checklist.
