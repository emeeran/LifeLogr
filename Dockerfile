# ── Stage 1: Build frontend ──
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ──
FROM python:3.11-alpine

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python deps (core only — no heavy system libs needed).
# `all` pulls the ocr/tts/image extras; `pdf` was never a valid extra name.
COPY backend/pyproject.toml backend/.python-version ./
RUN uv pip install --system -r pyproject.toml --extra all

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Copy assets
COPY assets/ ./assets/

WORKDIR /app/backend

# All durable state (SQLite DB + media + TTS cache) lives under DATA_DIR —
# mounting this one directory preserves everything across container
# replacement. DATABASE_URL/MEDIA_DIR derive from DATA_DIR when unset.
ENV APP_ENV=production
ENV DATA_DIR=/app/backend/data
RUN mkdir -p /app/backend/data
VOLUME ["/app/backend/data"]

# Bind 0.0.0.0 *inside* the container — required so the host port-forward in
# docker-compose.yml can reach the app. Host-side exposure is gated by the
# compose `ports:` mapping (bound to 127.0.0.1 by default). Do NOT widen that
# mapping without an authenticated reverse proxy in front.
EXPOSE 8000

# /health is the fast liveness path; APP_ENV=production keeps the boot-time
# SECRET_KEY / bind-host validations enabled (set both in backend/.env).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8000/health >/dev/null 2>&1 || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
