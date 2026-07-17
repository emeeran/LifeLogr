"""Web-page → markdown clipping (fallback when desktop image capture is off).

SSRF-hardened: blocks loopback / private / link-local / reserved / multicast
literal IPs and ``localhost``. Hostname DNS-rebinding protection is out of
scope here because the URL is typed by the local user (not an external
attacker); literal-IP blocking covers the common vectors (127.0.0.1, ::1,
169.254.169.254, RFC1918 ranges).

Uses ``html2text`` (pure-Python, no C deps) so it bundles cleanly under
PyInstaller — unlike lxml-based extractors.
"""

from __future__ import annotations

import ipaddress
import logging

import httpx

from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap on the fetched page body
_TIMEOUT_SECONDS = 10.0
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def _host_is_blocked(host: str) -> bool:
    """True if ``host`` is a literal internal/local IP or ``localhost``."""
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # hostname — allowed (no DNS-rebinding protection in v1)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _validate_url(url: httpx.URL) -> None:
    if url.scheme not in ("http", "https"):
        raise ValidationError("Only http/https URLs can be clipped.")
    if _host_is_blocked(url.host or ""):
        raise ValidationError("Clipping internal/local addresses is not allowed.")


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
    _validate_url(parsed)

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, follow_redirects=True
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
