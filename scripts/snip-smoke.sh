#!/usr/bin/env bash
# Environment + manual checklist for the Wayland screen-snip path (CAP-6).
#
# Usage: scripts/snip-smoke.sh
#
# This script is read-only: it inspects the session, the portal interface and
# the fallback tools, then prints the steps only a human can perform (portal
# prompts and region selection). It never captures the screen.
set -euo pipefail

echo "== Session =="
echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-<unset>}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>}"
echo "XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-<unset>}"

echo
echo "== Portal =="
if gdbus introspect --session \
    --dest org.freedesktop.portal.Desktop \
    --object-path /org/freedesktop/portal/desktop 2>/dev/null |
    grep -q 'org.freedesktop.portal.Screenshot'; then
  version=$(gdbus introspect --session \
    --dest org.freedesktop.portal.Desktop \
    --object-path /org/freedesktop/portal/desktop 2>/dev/null |
    grep -A2 'interface org.freedesktop.portal.Screenshot' |
    grep 'version' | grep -Eo '[0-9]+' | head -1)
  echo "Screenshot portal: present (version ${version:-unknown})"
else
  echo "Screenshot portal: MISSING — install xdg-desktop-portal-gnome"
fi

echo
echo "== Fallbacks =="
for tool in gnome-screenshot; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "$tool: $(command -v "$tool")"
  else
    echo "$tool: not installed (optional)"
  fi
done
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  echo "grim: not used on GNOME (needs wlr-screencopy, which GNOME does not implement)"
else
  echo "X11 session: xcap is used, portal is not"
fi

cat <<'NOTE'

== Manual checklist (desktop build) ==
1. Open a non-encrypted note → Notes.
2. Click the scissors button (or Ctrl+Shift+S).
3. FIRST use: the GNOME portal prompt appears → approve it.
   - If GNOME shows its own region selector, pick a region; the image is
     already cropped and the app's overlay just confirms it.
4. The crop overlay appears; select a region and release.
5. The image is embedded and OCR text appears beneath it.
6. Repeat once: no prompt should appear (permission is remembered).
7. Deny path: revoke the permission (Settings → Apps → LifeLogr) and repeat —
   expect a toast naming the portal failure, no stuck overlay.
8. X11 path: run `GDK_BACKEND=x11` with an X11 session — capture should use
   xcap and the overlay should show the full screen.
NOTE
