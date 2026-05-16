"""Student-facing class endpoints — joining a class by code.

`POST /v1/classes/join` lets any authenticated student request to join a
teacher's class with the class's `join_code` (`teacher-authoring.md` §9).
The request lands as a `pending` `class_members` row; the teacher then
approves it — the §14 consent checkpoint — via the teacher router.

The API talks to Supabase with the service-role key (which bypasses RLS),
so the new membership is scoped explicitly to the caller: the inserted
`student_id` is always `user["sub"]`. Joining is idempotent — a student
who already has a membership row (pending OR active) gets the current
state back, never a duplicate and never a downgrade of an active row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase

router = APIRouter(prefix="/classes", tags=["classes"])
log = get_logger(__name__)


class ClassJoin(BaseModel):
    """Request body for `POST /v1/classes/join`."""

    join_code: str = Field(min_length=1)


@router.post("/join")
async def join_class(
    body: ClassJoin,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Request to join a class by its `join_code` (`teacher-authoring.md` §9).

    Open to any authenticated user (a student). Looks up the `classes` row
    by `join_code` (matched case-insensitively — the input is upper-cased);
    an unknown code -> 404. Upserts a `class_members` row for the caller
    with `status='pending'`. Idempotent: if the caller already has a
    membership, its current `status` is returned unchanged — no duplicate
    row, no downgrade of an already-`active` membership.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    code = body.join_code.strip().upper()

    try:
        c_resp = (
            supabase.table("classes")
            .select("id,name,join_code")
            .eq("join_code", code)
            .limit(1)
            .execute()
        )
        classes = getattr(c_resp, "data", None) or []
        if not classes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
            )
        cls = classes[0]
        class_id = str(cls["id"])

        # Idempotency — if the caller already has a membership row, return
        # its current state rather than creating a duplicate or downgrading
        # an already-`active` membership back to `pending`.
        m_resp = (
            supabase.table("class_members")
            .select("status")
            .eq("class_id", class_id)
            .eq("student_id", caller_id)
            .limit(1)
            .execute()
        )
        existing = getattr(m_resp, "data", None) or []
        if existing:
            membership_status = existing[0].get("status") or "pending"
        else:
            membership_status = "pending"
            supabase.table("class_members").insert(
                {
                    "class_id": class_id,
                    "student_id": caller_id,
                    "status": "pending",
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                }
            ).execute()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("class_join_failed", error=str(e), student=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class join failed",
        ) from e

    return {
        "class_id": class_id,
        "class_name": cls.get("name"),
        "status": membership_status,
    }
