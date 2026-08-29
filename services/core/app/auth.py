"""Optional API-key auth for write endpoints.

Disabled by default (POMONA_API_KEY unset) so local development and the
documented quickstart keep working with no extra setup. Set API_KEY to
require an `Authorization: Bearer <key>` header on protected endpoints --
intended for any deployment reachable beyond localhost.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings


def require_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    if not settings.api_key:
        return
    expected = f"Bearer {settings.api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
