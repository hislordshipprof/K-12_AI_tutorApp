"""Session-ownership verification — guards against IDOR.

The API talks to Supabase with the service-role key (RLS bypassed), so any
endpoint that touches a `session_id` path param must explicitly verify that
the requesting user owns that session before reading or writing. This module
is the canonical place to do that.

Usage in a route:
    @router.post("/sessions/{session_id}/qa")
    async def ask_question(
        session_id: UUID,
        body: QAStreamRequest,
        session: Annotated[dict[str, Any], Depends(require_session_owner)],
        ...
    ):
        # `session` is guaranteed to be owned by the authenticated user.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled

log = get_logger(__name__)


def _user_id(user: dict[str, Any]) -> str:
    return str(user.get("sub") or "")


async def require_session_owner(
    session_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Dependency: 404 unless `user` owns `session_id`.

    Returns the session row (`id`, `user_id`, `topic_id`) on success.
    """
    user_id = _user_id(user)

    if not supabase_enabled():
        # No real DB wired — local dev path. The tutor agent's in-memory
        # cache keys sessions per-process and never crosses user boundaries
        # in practice, so allow through with a synthetic row.
        return {"id": str(session_id), "user_id": user_id, "topic_id": None}

    supabase = get_supabase()
    if supabase is None:
        # Same fallback as above; treat as "no DB".
        return {"id": str(session_id), "user_id": user_id, "topic_id": None}

    try:
        resp = (
            supabase.table("lesson_sessions")
            .select("id,user_id,topic_id")
            .eq("id", str(session_id))
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "session_owner_check_failed",
            error=str(e),
            session_id=str(session_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session lookup failed",
        ) from e

    if not rows:
        # Return 404 (not 403) so we don't leak whether the session exists
        # under a different user.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return rows[0]


def _is_uuid(value: str) -> bool:
    """True when `value` parses as a UUID."""
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


async def assert_session_owner_ws(
    session_id: UUID,
    user_id: str,
) -> bool:
    """Same check, but callable from a WebSocket handler (no DI graph).

    Returns True when the session is owned by `user_id`, False otherwise.
    In local-dev without Supabase the check is permissive.
    """
    if not supabase_enabled():
        return True
    supabase = get_supabase()
    if supabase is None:
        return True
    # The DEV_MODE shortcut accepts a connection as the synthetic
    # `dev-user`, which is not a UUID. Filtering Postgres' `uuid`
    # `user_id` column by a non-UUID string raises `22P02`; skip the
    # ownership check for non-UUID ids so the dev path closes cleanly
    # instead of erroring into a 4403.
    if not _is_uuid(user_id):
        log.info("session_owner_ws_skip_non_uuid", user_id=user_id)
        return True
    try:
        resp = (
            supabase.table("lesson_sessions")
            .select("id")
            .eq("id", str(session_id))
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return bool(getattr(resp, "data", None) or [])
    except Exception as e:  # noqa: BLE001
        log.warning(
            "session_owner_ws_check_failed",
            error=str(e),
            session_id=str(session_id),
        )
        return False
