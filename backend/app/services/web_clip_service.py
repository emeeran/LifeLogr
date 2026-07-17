"""Web-page → markdown clipping (fallback when desktop image capture is off).

SSRF-hardened for an **unauthenticated** loopback API — the destination host
is validated before EVERY hop, including HTTP redirects (via an httpx request
event hook), so a redirect to an internal address (``169.254.169.254`` cloud
metadata, ``127.0.0.1``, RFC1918, ``::1``, link-local) is blocked rather than
followed. Hostnames are also resolved and rejected if they resolve to any
internal IP (DNS-rebinding guard); unresolvable hosts are blocked fail-closed.

Uses ``html2text`` (pure-Python, no C deps) for clean PyInstaller bundling.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket

import httpx

from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024  # cap on the fetched page body
_TIMEOUT_SECONDS = 10.0
_MAX_REDIRECTS = 5
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def _ip_is_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _hostname_resolves_internal(host: str) -> bool:
    """True if ``host`` resolves to any internal IP (fail-closed if unresolvable).

    Guards against DNS-rebinding: a public-looking hostname that actually
    resolves to a private/loopback address.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # can't resolve → block
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError):
            continue
        if _ip_is_internal(ip):
            return True
    return False


async def _assert_safe_url(url: httpx.URL) -> None:
    """Raise ValidationError unless ``url`` points at a public host (per hop)."""
    if url.scheme not in ("http", "https"):
        raise ValidationError("Only http/https URLs can be clipped.")
    host = (url.host or "").lower().strip("[]")
    if not host or host == "localhost":
        raise ValidationError("Clipping internal/local addresses is not allowed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname → resolve to catch DNS-rebinding to internal IPs.
        if await asyncio.to_thread(_hostname_resolves_internal, host):
            raise ValidationError("Clipping internal/local addresses is not allowed.")
        return
    if _ip_is_internal(ip):
        raise ValidationError("Clipping internal/local addresses is not allowed.")


async def _request_guard(request: httpx.Request) -> None:
    """httpx request event hook — re-validate the host on every hop (redirects)."""
    await _assert_safe_url(request.url)


def _html_to_markdown(html: str) -> str:
    import html2text

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0  # don't hard-wrap lines
    return str(converter.handle(html)).strip()


async def extract_markdown_from_url(url: str) -> str:
    """Fetch ``url`` and return its content as markdown."""
    try:
        parsed = httpx.URL(url)
    except Exception as exc:  # malformed URL
        raise ValidationError("Invalid URL.") from exc

    try:
        # `follow_redirects` is safe here because `_request_guard` re-runs the
        # SSRF check (incl. DNS resolution) on every redirect target.
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            event_hooks={"request": [_request_guard]},
        ) as client:
            resp = await client.get(
                str(parsed), headers={"User-Agent": "LifeLogr/1.0 (+web clip)"}
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValidationError(f"Could not fetch page: {exc}") from exc

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if not content_type.startswith(_HTML_CONTENT_TYPES):
        raise ValidationError("Only HTML pages can be clipped.")

    return _html_to_markdown(resp.text[:_MAX_BYTES])
