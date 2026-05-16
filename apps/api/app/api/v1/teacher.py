"""Teacher-only endpoints — pipeline-job polling.

`GET /v1/teacher/jobs/{id}` lets the teacher board poll a `pipeline_jobs`
row's live `status` / `stage` while a minutes-long segment or generate job
runs in the background (`teacher-authoring.md` §10).

The route is gated by `require_role("teacher", "admin")`. Because the API
talks to Supabase with the service-role key — which bypasses RLS — this
handler ALSO verifies ownership explicitly: a job is owned by the teacher
who owns the course behind it (`teacher-authoring.md` §4 "RLS"):

  * a ``segment`` job  ->  `unit_id  -> units  -> courses.owner_id`
  * a ``generate`` job ->  `topic_id -> topics -> units -> courses.owner_id`

An `admin` may read any job. A teacher who is not the owner gets 404 (we
return 404 rather than 403 so the endpoint does not leak whether a job id
exists under another teacher).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_user_role, require_role
from app.core.supabase import get_supabase

router = APIRouter(prefix="/teacher", tags=["teacher"])
log = get_logger(__name__)


def _course_owner_for_job(supabase: Any, job: dict[str, Any]) -> str | None:
    """Resolve the `courses.owner_id` that owns this pipeline job.

    Walks the §4 ownership chain. Returns the owner's user id, or None
    when the chain cannot be resolved (a job with no unit/topic, or a
    dangling FK).
    """

    def _one(table: str, key: str, value: Any, columns: str) -> dict[str, Any] | None:
        resp = (
            supabase.table(table)
            .select(columns)
            .eq(key, value)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return rows[0] if rows else None

    unit_id = job.get("unit_id")
    if job.get("kind") != "segment" and job.get("topic_id"):
        # generate job: topic -> unit.
        topic = _one("topics", "id", job["topic_id"], "id,unit_id")
        if topic is None:
            return None
        unit_id = topic.get("unit_id")

    if not unit_id:
        return None

    unit = _one("units", "id", unit_id, "id,course_id")
    if unit is None or not unit.get("course_id"):
        return None

    course = _one("courses", "id", unit["course_id"], "id,owner_id")
    if course is None:
        return None
    return course.get("owner_id")


@router.get("/jobs/{job_id}")
async def get_pipeline_job(
    job_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Poll a `pipeline_jobs` row's live `status` / `stage`.

    Teacher/admin-gated. A teacher may only read jobs for courses they
    own; an admin may read any. Missing or non-owned job -> 404.
    """
    supabase = get_supabase()
    if supabase is None:
        # No DB wired (local-dev placeholder) — there is no job store.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )

    try:
        resp = (
            supabase.table("pipeline_jobs")
            .select("id,kind,unit_id,topic_id,status,stage,error")
            .eq("id", str(job_id))
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_job_lookup_failed", error=str(e), job_id=str(job_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="job lookup failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    job = rows[0]

    # Ownership check — the service role bypassed RLS, so enforce it here.
    caller_id = str(user.get("sub") or "")
    if get_user_role(caller_id) != "admin":
        owner_id = _course_owner_for_job(supabase, job)
        if owner_id is None or str(owner_id) != caller_id:
            # 404 (not 403) so we don't leak that the job exists.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="job not found",
            )

    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "unit_id": job.get("unit_id"),
        "topic_id": job.get("topic_id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "error": job.get("error"),
    }
