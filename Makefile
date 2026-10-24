# ─── LifeLogr Makefile ───────────────────────────────────────────────────────
SHELL := /bin/bash
BACKEND := backend
PYTHON  := $(BACKEND)/.venv/bin/python
UV      := uv
FE      := frontend

.PHONY: help setup test lint fe-test fe-typecheck fe-lint fe-build check run clean bump check-version docs-check

help:
	@echo ""
	@echo "  LifeLogr Commands"
	@echo "  ─────────────────────────────────────────"
	@echo "  make setup        Install / sync dependencies"
	@echo "  make test         Run backend tests"
	@echo "  make lint         Ruff + mypy (backend)"
	@echo "  make fe-test      Run frontend vitest suite"
	@echo "  make fe-typecheck Frontend vue-tsc build check"
	@echo "  make fe-lint      Frontend ESLint (if installed)"
	@echo "  make fe-build     Frontend production build"
	@echo "  make check        Everything CI runs (backend + frontend)"
	@echo "  make run          Start dev server"
	@echo "  make bump V=x    Bump version in all 4 places"
	@echo "  make check-version  Verify all 4 version sources match"
	@echo "  make docs-check     Verify docs don't reference a stale version"
	@echo "  make clean        Remove __pycache__ and .pytest_cache"
	@echo ""

setup:
	cd $(BACKEND) && $(UV) sync
	cd $(FE) && npm ci

test:
	cd $(BACKEND) && $(UV) run pytest tests/ -v --tb=short

lint:
	cd $(BACKEND) && $(UV) run ruff check . && $(UV) run mypy app/

fe-test:
	cd $(FE) && npm test

fe-typecheck:
	cd $(FE) && ./node_modules/.bin/vue-tsc -b

fe-lint:
	cd $(FE) && if [ -x ./node_modules/.bin/eslint ]; then ./node_modules/.bin/eslint src; else echo "eslint not installed — run: cd frontend && npm install -D eslint eslint-plugin-vue"; fi

fe-build:
	cd $(FE) && npm run build

# Mirrors .github/workflows/ci.yml so `make check` is the pre-push gate.
check: lint test fe-typecheck fe-test fe-lint

run:
	cd $(BACKEND) && $(UV) run uvicorn app.main:app --reload --port 8000

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true

bump:
	@if [ -z "$(V)" ]; then echo "Usage: make bump V=0.3.0"; exit 1; fi
	@echo "Bumping version to $(V) in 4 places..."
	@# 1. backend/pyproject.toml
	sed -i 's/^version = ".*"/version = "$(V)"/' backend/pyproject.toml
	@# 2. backend/app/core/config.py (APP_VERSION)
	sed -i 's/APP_VERSION: str = "[^"]*"/APP_VERSION: str = "$(V)"/' backend/app/core/config.py
	@# 3. desktop/src-tauri/Cargo.toml
	sed -i 's/^version = "[0-9.]*"/version = "$(V)"/' desktop/src-tauri/Cargo.toml
	@# 4. desktop/src-tauri/tauri.conf.json
	sed -i 's/"version": "[0-9.]*"/"version": "$(V)"/' desktop/src-tauri/tauri.conf.json
	@echo "✔ Version bumped to $(V). Verify with: git diff"

check-version:
	@python scripts/check_version.py

# Version strings in user-facing docs must match the release version
# (frontend/package.json is the source of truth). Checks the three places docs
# name a version: artifact filenames (LifeLogr_<v>_…, lifelogr-web_<v>_…),
# doc headers (*Version <v>* / README's `v<v>` badge), and the APP_VERSION row
# in ARCHITECTURE.md's config table. Example commands in docs (e.g.
# `git tag v1.0.0`) are deliberately excluded.
DOC_FILES := README.md docs/ARCHITECTURE.md docs/BUILD_GUIDE.md \
             docs/manual/USER_MANUAL.md docs/manual/DEPLOYMENT.md docs/manual/API_REFERENCE.md
DOC_VERSION_RE := (LifeLogr\|lifelogr-web)_[0-9]+\.[0-9]+\.[0-9]+_\|^\*Version [0-9]+\.[0-9]+\.[0-9]+\|^\`v[0-9]+\.[0-9]+\.[0-9]+\`\|APP_VERSION\` | \`[0-9]+\.[0-9]+\.[0-9]+

docs-check:
	@CURRENT="$$(node -p "require('./frontend/package.json').version" 2>/dev/null)"; \
	[ -n "$$CURRENT" ] || CURRENT="$$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' frontend/package.json | head -n1)"; \
	if [ -z "$$CURRENT" ]; then \
	  echo "docs-check: cannot read version from frontend/package.json" >&2; exit 1; fi; \
	STALE="$$(grep -hoE '$(DOC_VERSION_RE)' $(DOC_FILES) \
	  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -u | grep -vx "$$CURRENT" || true)"; \
	if [ -n "$$STALE" ]; then \
	  echo "docs-check: FAILED — docs reference a version other than $$CURRENT:"; \
	  echo "$$STALE" | sed 's/^/  /'; \
	  grep -n "$$STALE" $(DOC_FILES) | head -20 >&2 || true; \
	  exit 1; \
	fi; \
	echo "docs-check: OK — docs match version $$CURRENT"
