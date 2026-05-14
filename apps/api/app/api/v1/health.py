"""Authenticated health endpoint (in addition to the unauthenticated
`GET /health` defined directly on the app)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import get_current_user

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def authed_health(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Authenticated health check — confirms JWT verification works end-to-end."""
    return {
        "ok": True,
        "user_id": user.get("sub"),
        "models": settings.model_map,
    }
