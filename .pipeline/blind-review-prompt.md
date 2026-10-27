# Cold review dispatch (paste into a brand-new session, fresh terminal)

You're doing due diligence on this codebase before your team takes over
on-call for it. It's LifeLogr, a privacy-first local-first journaling + notes
app for Linux (Python 3.11/FastAPI backend in `backend/app/`, Vue 3 + TS
frontend in `frontend/src/`, Tauri v2 shell in `desktop/`), built as a
single-user app whose backend binds to 127.0.0.1.

Review it as a senior engineer seeing it for the first time. Explore the tree
yourself (backend tests run with `cd backend && uv run pytest tests/ -q`;
frontend with `npm test --prefix frontend`; lint with `make lint` and
`make fe-lint`). Flag anything inconsistent, templated or
AI-generated-looking, over-engineered, under-tested, or not
production-ready, with specific file:line references. Write your findings
verbatim to `.pipeline/blind-review.md` when done — do not soften or
reorganize them; the raw output is what gets reconciled against the team's
existing audit notes.
