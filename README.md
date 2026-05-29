# 📔 DailyByte (Diarilinux)

DailyByte is a privacy-first, offline-first journaling application designed for Linux (Ubuntu 24.x LTS) with native packaging capabilities. It provides a highly premium writing experience with markdown support, media attachments, local voice transcription, local AI-assisted grammar checking and mood insights, end-to-end encrypted cloud sync, and a dynamic plugin architecture—keeping all user data strictly local and secure.

---

## 🏗️ Architecture Overview

The project is structured as a multi-platform application:
*   **Backend (`backend/`):** FastAPI async server with SQLAlchemy 2.x and SQLite (WAL mode). Handles entry indexing, full-text FTS5/semantic vector hybrid search, local machine learning models (Ollama, Tesseract, Whisper), and backup sync.
*   **Frontend (`frontend/`):** Vue 3 SPA built with Vite, TypeScript, Pinia, and TailwindCSS v4. Featuring highly custom, accessible (WCAG compliant) dashboard, timeline, map, and calendar views.
*   **Desktop Wrapper (`desktop/`):** Tauri v2 Rust application wrapping the Vue frontend and bundling the Python backend as a packaged native sidecar binary.
*   **Mobile App (`mobile/`):** Scaffolding and Capacitor setups for potential mobile porting.

---

## ⚡ Quick Start

### 1. Pre-requisites
*   **Python 3.11+**
*   **Node.js 20+**
*   **Rust (stable)**
*   **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
*   **Ollama** (for semantic search & AI insights)
*   **Tesseract OCR** (for image text extraction)

### 2. Development Setup

Start backend services:
```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Start web frontend:
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🧪 Testing

The backend includes a highly comprehensive unit and integration test suite (130 tests) achieving **100% test passes** in `43.50s`:

```bash
cd backend
uv run pytest tests/ -v
```

---

## 📑 SDD Pipeline & Project Documentation

All system design blueprints are generated using Spec-Driven Development (SDD) pipelines:

| Phase | Command | Document | Purpose |
| :--- | :--- | :--- | :--- |
| **p0** | `make domain` | [DOMAIN.md](docs/00-domain/DOMAIN.md) | Bounded contexts & domain models |
| **p1** | `make reqs` | [REQUIREMENTS.md](docs/01-requirements/REQUIREMENTS.md) | Functional & Non-functional requirements |
| **p2** | `make spec` | [SPEC.md](docs/02-spec/SPEC.md) | Full schema models & API endpoints contract |
| **p3** | `make review` | [REVIEW.md](docs/03-review/REVIEW.md) | Quality gate checklist (Pass required) |
| **p4** | `make design` | [DESIGN.md](docs/04-design/DESIGN.md) | Module mapping & sequence diagrams |
| **p6** | `make test` | [BUILD_GUIDE.md](docs/BUILD_GUIDE.md) | Comprehensive compile and deployment guide |

### 🔍 Project Review & Enhancements
A detailed, Obsidian-compatible architectural analysis, test verification report, and code-level enhancement blueprint can be found here:
*   [agy_review_280526.md](.local/agy_review_280526.md)
