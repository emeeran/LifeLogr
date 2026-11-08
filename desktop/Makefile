.PHONY: install build build-frontend build-backend build-sidecar clean dev setup

# Linux-only app: one triple, no platform detection.
TRIPLE  := x86_64-unknown-linux-gnu
TARGETS := appimage,deb

# Tauri resolves `externalBin` ("lifelogr-backend") relative to the src-tauri/
# directory root, appending the target triple. The sidecar MUST live at
# src-tauri/lifelogr-backend-<triple> — not under binaries/ — or the stale
# build gets bundled.
SIDECAR := src-tauri/lifelogr-backend-$(TRIPLE)

# ── Prerequisites ──
install:
	rustup default stable
	cd ../frontend && npm install
	cd ../backend && uv sync

# ── Development ──
dev:
	cd ../frontend && npm run dev

# ── Build steps ──
build-frontend:
	@VER=$$(grep '^version' src-tauri/Cargo.toml | head -1 | sed 's/.*"\(.*\)".*/\1/'); \
		echo "Building frontend with VITE_APP_VERSION=$$VER"; \
		cd ../frontend && VITE_APP_VERSION="$$VER" npm run build

build-backend:
	cd ../backend && uv run pyinstaller ../desktop/scripts/pyinstaller.spec \
	    --noconfirm \
	    --distpath ../desktop/dist \
	    --workpath ../desktop/build/pyinstaller

build-sidecar: build-backend
	cp dist/lifelogr-backend$(EXE) $(SIDECAR)
	-chmod +x $(SIDECAR)
	@echo "Sidecar ready: $(SIDECAR)"

build: build-frontend build-sidecar
	cd src-tauri && cargo tauri build --bundles $(TARGETS)
	@echo ""
	@echo "Packages ready: src-tauri/target/release/bundle/"

# ── Setup (install system deps on Linux) ──
setup:
	sudo bash scripts/setup-linux.sh

# ── Clean ──
clean:
	rm -rf dist/ build/ src-tauri/target/
