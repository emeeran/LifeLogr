.PHONY: install build build-frontend build-backend build-sidecar clean dev setup

# ── Platform detection ──
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

ifeq ($(UNAME_S),Linux)
    TRIPLE   := x86_64-unknown-linux-gnu
    TARGETS  := appimage,deb
    EXE      :=
endif
ifeq ($(UNAME_S),Darwin)
    ifeq ($(UNAME_M),arm64)
        TRIPLE := aarch64-apple-darwin
    else
        TRIPLE := x86_64-apple-darwin
    endif
    TARGETS  := dmg
    EXE      :=
endif
ifeq ($(OS),Windows_NT)
    TRIPLE   := x86_64-pc-windows-msvc
    TARGETS  := msi
    EXE      := .exe
endif

SIDECAR := src-tauri/binaries/lifelogr-backend-$(TRIPLE)$(EXE)

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
	cd ../frontend && npm run build

build-backend:
	cd ../backend && uv run pyinstaller ../desktop/scripts/pyinstaller.spec \
	    --noconfirm \
	    --distpath ../desktop/dist \
	    --workpath ../desktop/build/pyinstaller

build-sidecar: build-backend
	@mkdir -p src-tauri/binaries
	cp dist/lifelogr-backend$(EXE) $(SIDECAR)
	cp dist/lifelogr-backend$(EXE) src-tauri/lifelogr-backend-$(TRIPLE)$(EXE)
	-chmod +x $(SIDECAR) src-tauri/lifelogr-backend-$(TRIPLE)$(EXE)
	@echo "Sidecar ready: $(SIDECAR)"

build: build-frontend build-sidecar
	cd src-tauri && cargo tauri build --bundles $(TARGETS)
	@echo ""
	@echo "Packages ready: src-tauri/target/release/bundle/"

# ── Setup (install system deps on Linux) ──
setup:
	@if [ "$(UNAME_S)" = "Linux" ]; then \
	    sudo bash scripts/setup-linux.sh; \
	else \
	    echo "System setup is only available on Linux."; \
	fi

# ── Clean ──
clean:
	rm -rf dist/ build/ src-tauri/target/
