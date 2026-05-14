"""Lesson session stubs — actual Supabase persistence wired by a later agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import SessionOut, SessionStartRequest

router = APIRouter(tags=["sessions"])

# In-memory store for the stub — replaced by Supabase later.
_SESSIONS: dict[UUID, dict[str, Any]] = {}


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def start_session(
    body: SessionStartRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Begin a tutoring session for the given topic."""
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    record = {
        "id": session_id,
        "user_id": UUID(user["sub"]) if _looks_like_uuid(user.get("sub")) else uuid4(),
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
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    record = _SESSIONS.get(session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return record


def _looks_like_uuid(s: Any) -> bool:
    try:
        UUID(str(s))
    except (ValueError, AttributeError, TypeError):
        return False
    return True
