"""Lesson session endpoints — Supabase-backed (with dev fallback)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import SessionOut, SessionStartRequest

router = APIRouter(tags=["sessions"])
log = get_logger(__name__)


# Process-local fallback (dev only).
_SESSIONS: dict[UUID, dict[str, Any]] = {}


def _looks_like_uuid(s: Any) -> bool:
    try:
        UUID(str(s))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _user_uuid(user: dict[str, Any]) -> UUID:
    sub = user.get("sub")
    if _looks_like_uuid(sub):
        return UUID(str(sub))
    return uuid4()


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    body: SessionStartRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Begin a tutoring session for the given topic."""
    user_id = _user_uuid(user)
    now = datetime.now(timezone.utc)

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("lesson_sessions")
                .insert(
                    {
                        "user_id": str(user_id),
                        "topic_id": str(body.topic_id),
                        "agent_state": {},
                    }
                )
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise RuntimeError("insert returned no rows")
        except Exception as e:  # noqa: BLE001
            log.warning("session_create_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="session creation unavailable",
                ) from e

    # Dev fallback.
    session_id = uuid4()
    record = {
        "id": session_id,
        "user_id": user_id,
        "topic_id": body.topic_id,
        "started_at": now,
        "ended_at": None,
        "agent_state": {},
        "created_at": now,
    }
    _SESSIONS[session_id] = record
    return record


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    user_id = _user_uuid(user)

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("lesson_sessions")
                .select("*")
                .eq("id", str(session_id))
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("session_get_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="session unavailable",
                ) from e

    record = _SESSIONS.get(session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return record
