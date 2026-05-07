# diary — Claude Context

## Project Purpose
> [Edit this: one paragraph describing what this project does and for whom.]

## Tech Stack
| Layer     | Technology                          |
|-----------|-------------------------------------|
| Backend   | Python 3.11+, FastAPI, Pydantic v2  |
| Database  | SQLite (dev) / PostgreSQL (prod)    |
| Packaging | `uv` (never use pip directly)       |
| Testing   | pytest, httpx, pytest-asyncio       |
| Linting   | ruff, mypy (strict)                 |
| OS        | Ubuntu 24.x                         |

## SDD Pipeline
```
p0: Domain  →  p1: Requirements  →  p2: Spec  →  p3: Review (PASS gate)
→  p4: Design  →  p5: Code  →  p5.5: Code Review  →  p6: Tests
```
**The review gate is hard.** Do not proceed to p4 until p3 outputs PASS.

## Key Commands
```bash
make setup        # Install dependencies
make domain       # Run domain analysis (p0)
make reqs         # Generate requirements (p1)
make spec         # Generate spec (p2)
make review       # Run review gate (p3) — must PASS before continuing
make design       # Generate design (p4)
make code         # Implement code (p5)
make review-code  # Review code for bloat (p5.5)
make test         # Run tests (p6)
make lint         # ruff + mypy
make run          # Start dev server
```

## Project Structure
```
diary/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI entry point
│   │   ├── core/            # Config, DB session, security
│   │   ├── routers/         # Route handlers
│   │   ├── models/          # ORM models
│   │   ├── schemas/         # Pydantic schemas
│   │   └── services/        # Business logic
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── .env                 # Local secrets (never commit)
│   └── pyproject.toml
├── docs/                    # SDD artefacts
├── prompts/                 # Prompt templates
├── raw_idea.txt
├── CLAUDE.md                # ← You are here
└── Makefile
```

## Conventions
- All secrets go in `backend/.env` — never hardcode.
- `uv add <pkg>` to add dependencies; `uv run pytest` to run tests.
- Commit docs artefacts (DOMAIN.md, SPEC.md, etc.) alongside code.
- Each PR must include updated tests and passing lint.
