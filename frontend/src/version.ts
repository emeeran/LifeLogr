/**
 * The app version, injected at build time via the VITE_APP_VERSION env var.
 *
 * This is the single source of truth for the bundled frontend: it always
 * matches the .deb / AppImage version because the build pipeline passes the
 * version from `desktop/src-tauri/Cargo.toml` in. We avoid a stale hardcoded
 * fallback (which previously showed "0.2.0" forever) and we don't depend on
 * the backend `/settings` round-trip having completed before rendering.
 *
 * The backend also reports `APP_VERSION` via `/api/v1/settings` for API
 * consumers; at runtime a component may prefer that value but should always
 * fall back to this build-time constant.
 */
export const APP_VERSION: string =
  (import.meta.env.VITE_APP_VERSION as string | undefined) ?? 'unknown'
