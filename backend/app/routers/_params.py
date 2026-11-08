"""Shared query-parameter parsing for routers."""

from __future__ import annotations

from fastapi import HTTPException


def parse_tag_ids(tag_ids: str | None) -> list[int] | None:
    """Parse a comma-separated ``tag_ids`` query param into tag IDs.

    Raises 422 (not a 500) on non-integer items, and treats an all-empty
    value (``tag_ids=,``) as no filter.
    """
    if not tag_ids:
        return None
    try:
        parsed = [int(t) for t in tag_ids.split(",") if t]
    except ValueError:
        raise HTTPException(
            status_code=422, detail="tag_ids must be comma-separated integers"
        ) from None
    return parsed or None
