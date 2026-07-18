"""Shared OAuth result page for the cloud-provider callback routers."""

import html

from fastapi.responses import HTMLResponse


def result_page(provider: str, ok: bool, detail: str = "") -> HTMLResponse:
    """Render the post-OAuth success/failure page shown in the browser."""
    title = f"{provider} Connected" if ok else "Connection Failed"
    emoji = "✅" if ok else "❌"
    body = (
        f"LifeLogr connected to your {provider} account. You can close this tab."
        if ok
        else html.escape(detail)
    )
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><body style='font-family:sans-serif;background:#0f172a;color:#f8fafc;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center'>"
            f"<div><div style='font-size:3rem'>{emoji}</div><h2>{title}</h2>"
            f"<p style='color:#94a3b8'>{body}</p></div></body></html>"
        ),
        status_code=200 if ok else 400,
    )
