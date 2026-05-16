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


@router.get("/classes")
async def list_teacher_classes(
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> list[dict[str, Any]]:
    """List the caller's non-archived classes with student counts.

    Powers the teacher home page (`/teach`) class list
    (`teacher-authoring.md` §9). Teacher/admin-gated. The service-role
    client bypasses RLS, so every query is scoped to the caller
    explicitly: an admin still only sees their OWN classes here.

    Each item:
        {"id", "name", "join_code", "subject", "student_count",
         "pending_count"}

    `student_count` / `pending_count` are `class_members` rows for the
    class with `status` 'active' / 'pending' respectively. A teacher with
    no classes gets `[]` (HTTP 200).
    """
    supabase = get_supabase()
    if supabase is None:
        return []

    caller_id = str(user.get("sub") or "")
    try:
        c_resp = (
            supabase.table("classes")
            .select("id,name,join_code,subject,archived")
            .eq("teacher_id", caller_id)
            .execute()
        )
        rows = getattr(c_resp, "data", None) or []
        classes = [c for c in rows if not c.get("archived")]
        if not classes:
            return []

        class_ids = [str(c["id"]) for c in classes]
        m_resp = (
            supabase.table("class_members")
            .select("class_id,status")
            .in_("class_id", class_ids)
            .execute()
        )
        members = getattr(m_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("teacher_classes_lookup_failed", error=str(e), teacher=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="classes lookup failed",
        ) from e

    active: dict[str, int] = {}
    pending: dict[str, int] = {}
    for m in members:
        cid = str(m.get("class_id"))
        if m.get("status") == "active":
            active[cid] = active.get(cid, 0) + 1
        elif m.get("status") == "pending":
            pending[cid] = pending.get(cid, 0) + 1

    return [
        {
            "id": str(c["id"]),
            "name": c.get("name"),
            "join_code": c.get("join_code"),
            "subject": c.get("subject"),
            "student_count": active.get(str(c["id"]), 0),
            "pending_count": pending.get(str(c["id"]), 0),
        }
        for c in classes
    ]


@router.get("/courses")
async def list_teacher_courses(
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> list[dict[str, Any]]:
    """List the caller's courses with unit/topic aggregate counts.

    Powers the teacher home page (`/teach`) course list
    (`teacher-authoring.md` §9). Teacher/admin-gated. The service-role
    client bypasses RLS, so the query is scoped to the caller explicitly
    via `courses.owner_id`: an admin still only sees their OWN courses.

    Each item:
        {"id", "title", "subject", "grade_band", "unit_count",
         "topic_count", "published_count", "draft_count", "icon_emoji",
         "color_gradient"}

    `unit_count` is `units` for the course; `topic_count` is `topics`
    under those units; `published_count` / `draft_count` split topics by
    `status`. A teacher with no courses gets `[]` (HTTP 200).
    """
    supabase = get_supabase()
    if supabase is None:
        return []

    caller_id = str(user.get("sub") or "")
    try:
        c_resp = (
            supabase.table("courses")
            .select("id,title,subject,grade_band,icon_emoji,color_gradient")
            .eq("owner_id", caller_id)
            .execute()
        )
        courses = getattr(c_resp, "data", None) or []
        if not courses:
            return []

        course_ids = [str(c["id"]) for c in courses]
        u_resp = (
            supabase.table("units")
            .select("id,course_id")
            .in_("course_id", course_ids)
            .execute()
        )
        units = getattr(u_resp, "data", None) or []

        topics: list[dict[str, Any]] = []
        if units:
            unit_ids = [str(u["id"]) for u in units]
            t_resp = (
                supabase.table("topics")
                .select("id,unit_id,status")
                .in_("unit_id", unit_ids)
                .execute()
            )
            topics = getattr(t_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("teacher_courses_lookup_failed", error=str(e), teacher=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="courses lookup failed",
        ) from e

    # unit_id -> course_id, so topic counts can be rolled up to the course.
    course_of_unit = {str(u["id"]): str(u["course_id"]) for u in units}

    unit_count: dict[str, int] = {}
    for u in units:
        cid = str(u["course_id"])
        unit_count[cid] = unit_count.get(cid, 0) + 1

    topic_count: dict[str, int] = {}
    published_count: dict[str, int] = {}
    draft_count: dict[str, int] = {}
    for t in topics:
        cid = course_of_unit.get(str(t.get("unit_id")))
        if cid is None:
            continue
        topic_count[cid] = topic_count.get(cid, 0) + 1
        if t.get("status") == "published":
            published_count[cid] = published_count.get(cid, 0) + 1
        elif t.get("status") == "draft":
            draft_count[cid] = draft_count.get(cid, 0) + 1

    return [
        {
            "id": str(c["id"]),
            "title": c.get("title"),
            "subject": c.get("subject"),
            "grade_band": c.get("grade_band"),
            "unit_count": unit_count.get(str(c["id"]), 0),
            "topic_count": topic_count.get(str(c["id"]), 0),
            "published_count": published_count.get(str(c["id"]), 0),
            "draft_count": draft_count.get(str(c["id"]), 0),
            "icon_emoji": c.get("icon_emoji"),
            "color_gradient": c.get("color_gradient"),
        }
        for c in courses
    ]
