# ── Stage 1: Build frontend ──
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ──
FROM python:3.11-slim

# System deps for WeasyPrint, Tesseract, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev libcairo2 shared-mime-info tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python deps
COPY backend/pyproject.toml backend/.python-version ./
RUN uv pip install --system -r pyproject.toml

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Copy assets
COPY assets/ ./assets/

# Create media directory
RUN mkdir -p media

WORKDIR /app/backend

ENV APP_ENV=production
ENV DATABASE_URL=sqlite+aiosqlite:///./prod.db
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
