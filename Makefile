# ─── LifeLogr Makefile ───────────────────────────────────────────────────────
SHELL := /bin/bash
BACKEND := backend
PYTHON  := $(BACKEND)/.venv/bin/python
UV      := uv

.PHONY: help setup test lint run clean bump check-version

help:
	@echo ""
	@echo "  LifeLogr Commands"
	@echo "  ─────────────────────────────────────────"
	@echo "  make setup        Install / sync dependencies"
	@echo "  make test         Run tests"
	@echo "  make lint         Ruff + mypy"
	@echo "  make run          Start dev server"
	@echo "  make bump V=x    Bump version in all 4 places"
	@echo "  make check-version  Verify all 4 version sources match"
	@echo "  make clean        Remove __pycache__ and .pytest_cache"
	@echo ""

setup:
	cd $(BACKEND) && $(UV) sync

test:
	cd $(BACKEND) && $(UV) run pytest tests/ -v --tb=short

lint:
	cd $(BACKEND) && $(UV) run ruff check . && $(UV) run mypy app/

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
