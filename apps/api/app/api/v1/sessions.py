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


def _ensure_teacher_enrollment(
    supabase: Any, user_id: str, topic_id: str
) -> None:
    """Lazily enrol the student in a teacher course on first classroom open.

    `teacher-authoring.md` §4: the first time a student opens a teacher
    course we insert an `enrollments` row so the existing dashboard /
    progress / history queries work unchanged. Enrollment is NOT
    authorization (RLS still gates access via `class_members`), so this
    is best-effort — it never blocks or fails the session. Recommended
    courses are left alone (they self-enrol elsewhere).
    """
    try:
        t = (
            supabase.table("topics")
            .select("unit_id")
            .eq("id", topic_id)
            .limit(1)
            .execute()
        )
        t_rows = getattr(t, "data", None) or []
        if not t_rows or not t_rows[0].get("unit_id"):
            return
        u = (
            supabase.table("units")
            .select("course_id")
            .eq("id", t_rows[0]["unit_id"])
            .limit(1)
            .execute()
        )
        u_rows = getattr(u, "data", None) or []
        if not u_rows or not u_rows[0].get("course_id"):
            return
        course_id = str(u_rows[0]["course_id"])
        c = (
            supabase.table("courses")
            .select("origin")
            .eq("id", course_id)
            .limit(1)
            .execute()
        )
        c_rows = getattr(c, "data", None) or []
        if not c_rows or c_rows[0].get("origin") != "teacher":
            return
        existing = (
            supabase.table("enrollments")
            .select("id")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .limit(1)
            .execute()
        )
        if getattr(existing, "data", None):
            return
        supabase.table("enrollments").insert(
            {"user_id": user_id, "course_id": course_id}
        ).execute()
        log.info("teacher_enrollment_created", user=user_id, course=course_id)
    except Exception as e:  # noqa: BLE001
        log.warning("teacher_enrollment_failed", error=str(e), topic=topic_id)


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
                # First open of a teacher course → lazily create the
                # `enrollments` row (best-effort; never blocks the session).
                _ensure_teacher_enrollment(
                    supabase, str(user_id), str(body.topic_id)
                )
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
