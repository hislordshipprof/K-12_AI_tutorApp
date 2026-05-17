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

import functools
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from anyio import to_thread
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.rate_limit import RateLimitExceeded, ingest_acquire
from app.core.security import get_user_role, require_role
from app.core.supabase import get_supabase
from app.pipeline.confirm import ConfirmError, confirm_breakdown
from app.pipeline.ingest import IngestRejected, ingest_material, validate_upload
from app.pipeline.jobs import run_job
from app.pipeline.render import render_topic
from app.pipeline.segment import ProposedTopic, segment_unit
from app.pipeline.validate import generate_and_validate

router = APIRouter(prefix="/teacher", tags=["teacher"])
log = get_logger(__name__)


# ── Segment-job stage handlers (teacher-authoring.md §6) ────────────────────
# A `segment` job's stage sequence is `converting` -> `comprehending`
# (`jobs.STAGE_SEQUENCES`). `converting` stays UNREGISTERED — task 3.3
# already converts each material on upload, so it is a runner no-op here.
# `comprehending` runs the (minutes-long) multimodal comprehension call.
async def _comprehending_stage(job: dict[str, Any]) -> None:
    """Stage handler — comprehend the job's unit into a `unit_segmentations`
    row (`segment.segment_unit`)."""
    await segment_unit(str(job["unit_id"]))


_SEGMENT_HANDLERS = {"comprehending": _comprehending_stage}


# ── Generate-job stage handlers (teacher-authoring.md §6) ───────────────────
# A `generate` job's stage sequence is `rendering` -> `generating` ->
# `validating` (`jobs.STAGE_SEQUENCES`). `rendering` rasterises the topic's
# claimed slides; `generating` writes the lesson AND validates it (validation
# runs INSIDE `generate_and_validate`). `validating` therefore stays
# UNREGISTERED — it is a runner no-op.
async def _rendering_stage(job: dict[str, Any]) -> None:
    """Stage handler — render the topic's claimed slide/figure pages."""
    await render_topic(str(job["topic_id"]))


async def _generating_stage(job: dict[str, Any]) -> None:
    """Stage handler — generate + validate the topic's lesson, then persist
    the per-version validation result onto the `topic_versions` row the run
    produced so the publish gate + the topic page can read it (§6)."""
    result = await generate_and_validate(str(job["topic_id"]))
    r = result.report
    get_supabase().table("topic_versions").update(
        {
            "validation": {
                "passed": r.passed,
                "covered": r.covered,
                "total": r.total,
                "gaps": [
                    {
                        "section": g.section,
                        "key_point": g.key_point,
                        "verdict": g.verdict,
                        "detail": g.detail,
                    }
                    for g in r.gaps
                ],
            }
        }
    ).eq("id", result.generate.version_id).execute()


_GENERATE_HANDLERS = {
    "rendering": _rendering_stage,
    "generating": _generating_stage,
}

# Unambiguous join-code alphabet — no O/0/I/1 so a code is easy to read
# aloud and type (`teacher-authoring.md` §9).
_JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_JOIN_CODE_MAX_TRIES = 12


def _join_code_prefix(subject: str | None) -> str:
    """Derive the 4-char alpha prefix of a join code from `subject`.

    The first 4 alphabetic characters of `subject`, upper-cased; falls back
    to ``"CLAS"`` when `subject` is empty or has fewer than 4 letters.
    """
    letters = "".join(ch for ch in (subject or "") if ch.isalpha())
    if len(letters) < 4:
        return "CLAS"
    return letters[:4].upper()


def _make_join_code(subject: str | None) -> str:
    """Build a candidate join code: ``PREFIX-XXXX`` (e.g. ``PHYS-7K2M``)."""
    suffix = "".join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(4))
    return f"{_join_code_prefix(subject)}-{suffix}"


def _generate_unique_join_code(supabase: Any, subject: str | None) -> str:
    """Generate a join code not already present in `classes`.

    Retries up to ``_JOIN_CODE_MAX_TRIES`` times; raises ``HTTPException``
    503 if every candidate collides (vanishingly unlikely).
    """
    for _ in range(_JOIN_CODE_MAX_TRIES):
        code = _make_join_code(subject)
        resp = (
            supabase.table("classes")
            .select("id")
            .eq("join_code", code)
            .limit(1)
            .execute()
        )
        if not (getattr(resp, "data", None) or []):
            return code
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="could not allocate a unique join code",
    )


def _load_owned_class(
    supabase: Any, class_id: str, caller_id: str
) -> dict[str, Any]:
    """Load a `classes` row and enforce caller ownership (`§4` RLS).

    The service-role client bypassed RLS, so ownership is checked here: the
    caller must be the class's `teacher_id`, or an `admin`. A missing class
    OR a class owned by someone else both raise 404 (never 403) so the
    endpoint does not leak that the class id exists.
    """
    try:
        resp = (
            supabase.table("classes")
            .select("id,name,subject,join_code,teacher_id,archived")
            .eq("id", class_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("class_lookup_failed", error=str(e), class_id=class_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class lookup failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )
    cls = rows[0]
    if str(cls.get("teacher_id") or "") != caller_id and (
        get_user_role(caller_id) != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )
    return cls


def _load_owned_course(
    supabase: Any, course_id: str, caller_id: str
) -> dict[str, Any]:
    """Load a `courses` row and enforce caller ownership (`§4` RLS).

    The service-role client bypasses RLS, so ownership is checked here: the
    caller must be the course's `owner_id`, or an `admin`. A missing course
    OR a course owned by someone else both raise 404 (never 403) so the
    endpoint does not leak that the course id exists.
    """
    try:
        resp = (
            supabase.table("courses")
            .select("id,title,subject,grade_band,teaching_style,owner_id")
            .eq("id", course_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("course_lookup_failed", error=str(e), course_id=course_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course lookup failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
        )
    course = rows[0]
    if str(course.get("owner_id") or "") != caller_id and (
        get_user_role(caller_id) != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
        )
    return course


def _load_owned_unit(
    supabase: Any, unit_id: str, caller_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a `units` row and the `courses` row that owns it (`§4` RLS).

    A missing unit -> 404. The unit's course is then loaded via
    `_load_owned_course`, which enforces caller ownership the same way — a
    unit under a non-owned (or missing) course also 404s. Returns
    `(unit, course)`.
    """
    try:
        resp = (
            supabase.table("units")
            .select("id,course_id,n,name")
            .eq("id", unit_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("unit_lookup_failed", error=str(e), unit_id=unit_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unit lookup failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )
    unit = rows[0]
    course = _load_owned_course(supabase, str(unit.get("course_id")), caller_id)
    return unit, course


def _load_owned_topic(
    supabase: Any, topic_id: str, caller_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load a `topics` row + its `units` row + its owning `courses` row (`§4`).

    A missing topic -> 404. The topic's unit, then its course, are loaded the
    same way `_load_owned_unit` does — `_load_owned_course` enforces caller
    ownership, so a topic under a non-owned (or missing) course also 404s.
    Returns `(topic, unit, course)`.
    """
    try:
        resp = (
            supabase.table("topics")
            .select(
                "id,unit_id,n,name,summary,content,status,design_notes,"
                "active_version_id"
            )
            .eq("id", topic_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("topic_lookup_failed", error=str(e), topic_id=topic_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic lookup failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )
    topic = rows[0]
    unit, course = _load_owned_unit(supabase, str(topic.get("unit_id")), caller_id)
    return topic, unit, course


# Slug alphabet for the random suffix — lowercase letters + digits.
_SLUG_ALPHABET = string.ascii_lowercase + string.digits
_SLUG_MAX_TRIES = 12


def _slugify(title: str) -> str:
    """Slugify `title`: lowercase, collapse non-alphanumeric runs to one `-`,
    strip leading/trailing `-`, truncate to 40 chars; empty -> ``"course"``."""
    out: list[str] = []
    prev_dash = False
    for ch in title.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")[:40].strip("-")
    return slug or "course"


def _generate_unique_slug(supabase: Any, title: str) -> str:
    """Generate a `courses.slug` not already present in the table.

    Slugifies `title` and appends a `-` + 6 random chars. Retries up to
    ``_SLUG_MAX_TRIES`` times; raises ``HTTPException`` 503 if every
    candidate collides (vanishingly unlikely).
    """
    base = _slugify(title)
    for _ in range(_SLUG_MAX_TRIES):
        suffix = "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(6))
        slug = f"{base}-{suffix}"
        resp = (
            supabase.table("courses")
            .select("id")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        if not (getattr(resp, "data", None) or []):
            return slug
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="could not allocate a unique slug",
    )


def _student_email(supabase: Any, student_id: str) -> str | None:
    """Best-effort fetch of a student's email from `auth.users`.

    `profiles` has no email column (`teacher-authoring.md` §4); the address
    lives in `auth.users`. Any failure (admin API missing, network) yields
    None — a roster row without an email is fine, a crash is not.
    """
    try:
        result = supabase.auth.admin.get_user_by_id(student_id)
        user = getattr(result, "user", None) or result
        return getattr(user, "email", None)
    except Exception as e:  # noqa: BLE001
        log.warning("student_email_lookup_failed", error=str(e), student=student_id)
        return None


class ClassCreate(BaseModel):
    """Request body for `POST /v1/teacher/classes`."""

    name: str = Field(min_length=1)
    subject: str | None = None


class ClassCourseAssign(BaseModel):
    """Request body for `POST /v1/teacher/classes/{class_id}/courses`."""

    course_id: UUID


class CourseCreate(BaseModel):
    """Request body for `POST /v1/teacher/courses`."""

    title: str = Field(min_length=1)
    subject: str | None = None
    grade_band: str | None = None


class CourseUpdate(BaseModel):
    """Request body for `PATCH /v1/teacher/courses/{course_id}`.

    An empty `teaching_style` is allowed — it clears the course's style.
    """

    teaching_style: str


class UnitCreate(BaseModel):
    """Request body for `POST /v1/teacher/courses/{course_id}/units`."""

    name: str = Field(min_length=1)


class ConfirmTopicsRequest(BaseModel):
    """Request body for `POST /v1/teacher/units/{unit_id}/topics`.

    `topics` is the teacher's (possibly edited) breakdown — each element is
    a `ProposedTopic` (`segment.py`), so FastAPI validates the shape and a
    malformed topic 422s before the handler runs.
    """

    topics: list[ProposedTopic]


class TopicUpdate(BaseModel):
    """Request body for `PATCH /v1/teacher/topics/{topic_id}`.

    Both fields are optional — `None` means "leave unchanged". `design_notes`
    is the per-lesson teacher guidance; `content` is a hand-edited lesson, a
    list of `{tts, html, dur, scene, page?}` step dicts (§6).
    """

    design_notes: str | None = None
    content: list[dict[str, Any]] | None = None


class VersionLabelUpdate(BaseModel):
    """Request body for `PATCH /v1/teacher/topics/{id}/versions/{vid}` — the
    teacher's own name for a generated version (task 5.1)."""

    label: str = Field(min_length=1, max_length=80)


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


# ─── class management (`/teach/classes/[id]`, `teacher-authoring.md` §9) ───
@router.post("/classes", status_code=status.HTTP_201_CREATED)
async def create_class(
    body: ClassCreate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Create a class owned by the caller (`teacher-authoring.md` §9).

    Teacher/admin-gated. Inserts a `classes` row with `teacher_id` set to
    the caller, `archived=false`, and a freshly-generated UNIQUE
    `join_code`. The response shape mirrors a `GET /v1/teacher/classes`
    item (with zero counts) so the frontend can reuse it directly.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class store unavailable",
        )

    caller_id = str(user.get("sub") or "")
    try:
        join_code = _generate_unique_join_code(supabase, body.subject)
        payload = {
            "teacher_id": caller_id,
            "name": body.name,
            "subject": body.subject,
            "archived": False,
            "join_code": join_code,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        resp = supabase.table("classes").insert(payload).execute()
        rows = getattr(resp, "data", None) or []
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("class_create_failed", error=str(e), teacher=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class create failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class create failed",
        )
    created = rows[0]
    return {
        "id": str(created["id"]),
        "name": created.get("name"),
        "subject": created.get("subject"),
        "join_code": created.get("join_code"),
        "student_count": 0,
        "pending_count": 0,
    }


@router.get("/classes/{class_id}")
async def get_class_detail(
    class_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return a class's roster, pending join requests, and courses.

    Powers the teacher class-management screen (`teacher-authoring.md`
    §9). Teacher/admin-gated; ownership is enforced explicitly (the
    service role bypasses RLS) — a missing OR non-owned class -> 404.

    `roster` is `class_members` with `status='active'`; `pending` is
    `status='pending'`. Student `name` comes from `profiles.full_name`;
    `email` is a best-effort `auth.users` lookup per student.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    cls = _load_owned_class(supabase, str(class_id), caller_id)

    try:
        m_resp = (
            supabase.table("class_members")
            .select("student_id,status,requested_at,approved_at")
            .eq("class_id", str(class_id))
            .execute()
        )
        members = getattr(m_resp, "data", None) or []

        student_ids = [str(m["student_id"]) for m in members if m.get("student_id")]
        names: dict[str, str | None] = {}
        if student_ids:
            p_resp = (
                supabase.table("profiles")
                .select("id,full_name")
                .in_("id", student_ids)
                .execute()
            )
            for p in getattr(p_resp, "data", None) or []:
                names[str(p["id"])] = p.get("full_name")

        cc_resp = (
            supabase.table("class_courses")
            .select("course_id")
            .eq("class_id", str(class_id))
            .execute()
        )
        course_ids = [
            str(r["course_id"])
            for r in getattr(cc_resp, "data", None) or []
            if r.get("course_id")
        ]
        courses: list[dict[str, Any]] = []
        if course_ids:
            co_resp = (
                supabase.table("courses")
                .select("id,title")
                .in_("id", course_ids)
                .execute()
            )
            courses = [
                {"id": str(c["id"]), "title": c.get("title")}
                for c in getattr(co_resp, "data", None) or []
            ]
    except Exception as e:  # noqa: BLE001
        log.warning("class_detail_failed", error=str(e), class_id=str(class_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="class detail lookup failed",
        ) from e

    roster: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for m in members:
        sid = str(m.get("student_id") or "")
        common = {
            "student_id": sid,
            "name": names.get(sid),
            "email": _student_email(supabase, sid),
        }
        if m.get("status") == "active":
            roster.append({**common, "joined_at": m.get("approved_at")})
        elif m.get("status") == "pending":
            pending.append({**common, "requested_at": m.get("requested_at")})

    return {
        "id": str(cls["id"]),
        "name": cls.get("name"),
        "subject": cls.get("subject"),
        "join_code": cls.get("join_code"),
        "roster": roster,
        "pending": pending,
        "courses": courses,
    }


@router.post("/classes/{class_id}/members/{student_id}/approve")
async def approve_class_member(
    class_id: UUID,
    student_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Approve a pending student — the §14 consent checkpoint.

    Teacher/admin-gated; the class must be owned by the caller (or caller
    is admin) else 404. Flips the `class_members` row keyed
    (class_id, student_id) to `status='active'` and records
    `approved_by` / `approved_at` (`teacher-authoring.md` §14). No such
    membership row -> 404.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_class(supabase, str(class_id), caller_id)

    try:
        resp = (
            supabase.table("class_members")
            .update(
                {
                    "status": "active",
                    "approved_by": caller_id,
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("class_id", str(class_id))
            .eq("student_id", str(student_id))
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "class_member_approve_failed",
            error=str(e),
            class_id=str(class_id),
            student_id=str(student_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="member approve failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="member not found"
        )
    return {"ok": True}


@router.delete(
    "/classes/{class_id}/members/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_class_member(
    class_id: UUID,
    student_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> None:
    """Remove a student from a class (`teacher-authoring.md` §9).

    Teacher/admin-gated; the class must be owned by the caller (or caller
    is admin) else 404. Deletes the `class_members` row keyed
    (class_id, student_id) — this serves both declining a pending request
    and removing an active student. Returns HTTP 204.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_class(supabase, str(class_id), caller_id)

    try:
        (
            supabase.table("class_members")
            .delete()
            .eq("class_id", str(class_id))
            .eq("student_id", str(student_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "class_member_remove_failed",
            error=str(e),
            class_id=str(class_id),
            student_id=str(student_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="member remove failed",
        ) from e
    return None


# ─── course / unit authoring (`/teach/courses/[id]`, `teacher-authoring.md`
# §4/§6/§9) ────────────────────────────────────────────────────────────────
@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Create a teacher-authored course owned by the caller (`§9`).

    Teacher/admin-gated. Inserts a `courses` row with `owner_id` set to the
    caller, `origin='teacher'`, and a freshly-generated UNIQUE `slug`.
    `teaching_style` is left null — it is set later via PATCH. The response
    shape mirrors a `GET /v1/teacher/courses` item (with zero counts) so the
    frontend can reuse it directly.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course store unavailable",
        )

    caller_id = str(user.get("sub") or "")
    try:
        slug = _generate_unique_slug(supabase, body.title)
        payload = {
            "owner_id": caller_id,
            "origin": "teacher",
            "slug": slug,
            "title": body.title,
            "subject": body.subject,
            "grade_band": body.grade_band,
        }
        resp = supabase.table("courses").insert(payload).execute()
        rows = getattr(resp, "data", None) or []
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("course_create_failed", error=str(e), teacher=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course create failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course create failed",
        )
    created = rows[0]
    return {
        "id": str(created["id"]),
        "title": created.get("title"),
        "subject": created.get("subject"),
        "grade_band": created.get("grade_band"),
        "unit_count": 0,
        "topic_count": 0,
        "published_count": 0,
        "draft_count": 0,
        "icon_emoji": created.get("icon_emoji"),
        "color_gradient": created.get("color_gradient"),
    }


@router.get("/courses/{course_id}")
async def get_course_detail(
    course_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return a course's units with per-unit material counts (`§9`).

    Teacher/admin-gated; ownership is enforced explicitly (the service role
    bypasses RLS) — a missing OR non-owned course -> 404. Units are ordered
    by `n`; `material_count` is the `lesson_materials` rows under each unit.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
        )

    caller_id = str(user.get("sub") or "")
    course = _load_owned_course(supabase, str(course_id), caller_id)

    try:
        u_resp = (
            supabase.table("units")
            .select("id,n,name")
            .eq("course_id", str(course_id))
            .order("n")
            .execute()
        )
        units = getattr(u_resp, "data", None) or []

        material_count: dict[str, int] = {}
        if units:
            unit_ids = [str(u["id"]) for u in units]
            m_resp = (
                supabase.table("lesson_materials")
                .select("id,unit_id")
                .in_("unit_id", unit_ids)
                .execute()
            )
            for m in getattr(m_resp, "data", None) or []:
                uid = str(m.get("unit_id"))
                material_count[uid] = material_count.get(uid, 0) + 1
    except Exception as e:  # noqa: BLE001
        log.warning("course_detail_failed", error=str(e), course_id=str(course_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course detail lookup failed",
        ) from e

    return {
        "id": str(course["id"]),
        "title": course.get("title"),
        "subject": course.get("subject"),
        "grade_band": course.get("grade_band"),
        "teaching_style": course.get("teaching_style"),
        "units": [
            {
                "id": str(u["id"]),
                "n": u.get("n"),
                "name": u.get("name"),
                "material_count": material_count.get(str(u["id"]), 0),
            }
            for u in units
        ],
    }


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: UUID,
    body: CourseUpdate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Set a course's `teaching_style` (`§9`).

    Teacher/admin-gated; the course must be owned by the caller (or caller
    is admin) else 404. An empty `teaching_style` clears the style.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_course(supabase, str(course_id), caller_id)

    try:
        (
            supabase.table("courses")
            .update({"teaching_style": body.teaching_style})
            .eq("id", str(course_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning("course_update_failed", error=str(e), course_id=str(course_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course update failed",
        ) from e

    return {"id": str(course_id), "teaching_style": body.teaching_style}


@router.post("/courses/{course_id}/units", status_code=status.HTTP_201_CREATED)
async def create_unit(
    course_id: UUID,
    body: UnitCreate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Create a unit under a course (`§9`).

    Teacher/admin-gated; the course must be owned by the caller (or caller
    is admin) else 404. The new unit's `n` is one past the highest existing
    `n` in the course (the §4 `UNIQUE(course_id, n)` ordering).
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_course(supabase, str(course_id), caller_id)

    try:
        u_resp = (
            supabase.table("units")
            .select("n")
            .eq("course_id", str(course_id))
            .execute()
        )
        existing = getattr(u_resp, "data", None) or []
        next_n = max((u.get("n") or 0 for u in existing), default=0) + 1
        resp = (
            supabase.table("units")
            .insert(
                {
                    "course_id": str(course_id),
                    "n": next_n,
                    "name": body.name,
                }
            )
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("unit_create_failed", error=str(e), course_id=str(course_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unit create failed",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unit create failed",
        )
    created = rows[0]
    return {
        "id": str(created["id"]),
        "n": created.get("n"),
        "name": created.get("name"),
        "material_count": 0,
    }


@router.get("/units/{unit_id}")
async def get_unit_detail(
    unit_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return a unit's lesson materials, topics + its latest segment job (`§6`/`§9`).

    Teacher/admin-gated; the unit's course must be owned by the caller (or
    caller is admin) else 404. Materials are ordered by `uploaded_at`;
    `status` is the row's `conversion_status`. `topics` is the unit's
    `topics` rows ordered by `n`, each shaped `{id,n,name,status}`.
    `segment_job` is the unit's most recent `pipeline_jobs` row with
    `kind='segment'` (shaped `{id,status,stage}`) so the unit screen can show
    / poll segmentation progress — `null` when the unit has never been
    segmented.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    caller_id = str(user.get("sub") or "")
    unit, course = _load_owned_unit(supabase, str(unit_id), caller_id)

    try:
        m_resp = (
            supabase.table("lesson_materials")
            .select("id,filename,kind,conversion_status")
            .eq("unit_id", str(unit_id))
            .order("uploaded_at")
            .execute()
        )
        materials = getattr(m_resp, "data", None) or []

        t_resp = (
            supabase.table("topics")
            .select("id,n,name,status")
            .eq("unit_id", str(unit_id))
            .order("n")
            .execute()
        )
        topics = getattr(t_resp, "data", None) or []

        j_resp = (
            supabase.table("pipeline_jobs")
            .select("id,status,stage")
            .eq("unit_id", str(unit_id))
            .eq("kind", "segment")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        job_rows = getattr(j_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("unit_detail_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unit detail lookup failed",
        ) from e

    segment_job = (
        {
            "id": str(job_rows[0]["id"]),
            "status": job_rows[0].get("status"),
            "stage": job_rows[0].get("stage"),
        }
        if job_rows
        else None
    )

    return {
        "id": str(unit["id"]),
        "name": unit.get("name"),
        "course_id": str(course["id"]),
        "course_title": course.get("title"),
        "materials": [
            {
                "id": str(m["id"]),
                "filename": m.get("filename"),
                "kind": m.get("kind"),
                "status": m.get("conversion_status"),
            }
            for m in materials
        ],
        "topics": [
            {
                "id": str(t["id"]),
                "n": t.get("n"),
                "name": t.get("name"),
                "status": t.get("status"),
            }
            for t in topics
        ],
        "segment_job": segment_job,
    }


@router.post("/units/{unit_id}/materials")
async def upload_materials(
    unit_id: UUID,
    files: Annotated[list[UploadFile], File(...)],
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> list[dict[str, Any]]:
    """Upload one or more lesson materials to a unit (`§6` Ingest).

    Teacher/admin-gated; the unit's course must be owned by the caller (or
    caller is admin) else 404. Every file is pre-validated with
    `validate_upload` BEFORE any ingest runs, so a bad file in the batch
    does not leave the batch half-ingested. Each accepted file is
    rate-limited (`ingest_acquire` -> 429 on overflow) then ingested via
    `ingest_material` (a blocking sync call, run off the event loop).
    `kind` is left null — later segmentation proposes it (`§4`).
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_unit(supabase, str(unit_id), caller_id)

    # Read + pre-validate every file BEFORE ingesting any of them.
    pending: list[tuple[str, bytes, str | None]] = []
    for f in files:
        data = await f.read()
        filename = f.filename or ""
        try:
            validate_upload(filename, data, f.content_type)
        except IngestRejected as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{filename}: {exc}",
            ) from exc
        pending.append((filename, data, f.content_type))

    results: list[dict[str, Any]] = []
    for filename, data, claimed_mime in pending:
        try:
            await ingest_acquire(caller_id)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
            ) from exc
        result = await to_thread.run_sync(
            functools.partial(
                ingest_material,
                unit_id=str(unit_id),
                teacher_id=caller_id,
                filename=filename,
                data=data,
                claimed_mime=claimed_mime,
                kind=None,
            )
        )
        results.append(
            {
                "id": result.material_id,
                "filename": filename,
                "kind": None,
                "status": result.conversion_status,
            }
        )

    return results


# ─── segmentation pipeline (`/teach/.../breakdown`, `teacher-authoring.md`
# §6/§10/§13) ───────────────────────────────────────────────────────────────
@router.post(
    "/units/{unit_id}/segment", status_code=status.HTTP_202_ACCEPTED
)
async def segment_unit_endpoint(
    unit_id: UUID,
    background: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Enqueue a `segment` pipeline job for a unit (`§6`/`§10`).

    Teacher/admin-gated; the unit's course must be owned by the caller (or
    caller is admin) else 404. The unit must have at least one material and
    EVERY material must be `converted` — a still-converting material 400s
    (§13). At most one segment job runs per unit at a time: if a `queued`
    or `running` segment job already exists it is returned as-is, without
    starting another (§13). Otherwise a `pipeline_jobs` row is inserted and
    `run_job` walks it (the minutes-long comprehension call) in the
    background. Returns `{job_id, status}` with HTTP 202.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_unit(supabase, str(unit_id), caller_id)

    try:
        m_resp = (
            supabase.table("lesson_materials")
            .select("id,conversion_status")
            .eq("unit_id", str(unit_id))
            .execute()
        )
        materials = getattr(m_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("segment_materials_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="material lookup failed",
        ) from e

    if not materials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unit has no material to segment",
        )
    if any(m.get("conversion_status") != "converted" for m in materials):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="material is still converting",
        )

    try:
        # §13 — at most one in-flight segment job per unit. Return any
        # existing queued/running job instead of starting a second.
        inflight_resp = (
            supabase.table("pipeline_jobs")
            .select("id,status,stage,kind")
            .eq("unit_id", str(unit_id))
            .eq("kind", "segment")
            .in_("status", ["queued", "running"])
            .execute()
        )
        inflight = getattr(inflight_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("segment_job_lookup_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="segment job lookup failed",
        ) from e

    if inflight:
        existing = inflight[0]
        return {"job_id": str(existing["id"]), "status": existing.get("status")}

    try:
        await ingest_acquire(caller_id)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("pipeline_jobs").insert(
            {
                "id": job_id,
                "kind": "segment",
                "unit_id": str(unit_id),
                "status": "queued",
                "stage": None,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("segment_job_insert_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="segment job create failed",
        ) from e

    background.add_task(run_job, job_id, handlers=_SEGMENT_HANDLERS)
    return {"job_id": job_id, "status": "queued"}


@router.get("/units/{unit_id}/segmentation")
async def get_unit_segmentation(
    unit_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return a unit's latest proposed breakdown (`§5.7`/`§6`/`§10`).

    Teacher/admin-gated; the unit's course must be owned by the caller (or
    caller is admin) else 404. Powers the breakdown-review screen — the
    latest `unit_segmentations` row's proposed `topics`, the pages the
    comprehension stage `teach=false`-excluded, and the unit's materials
    (indexed in `uploaded_at` order, the order segmentation used). No
    segmentation row -> 404.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_unit(supabase, str(unit_id), caller_id)

    try:
        s_resp = (
            supabase.table("unit_segmentations")
            .select("id,comprehension,proposed,status,created_at")
            .eq("unit_id", str(unit_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        seg_rows = getattr(s_resp, "data", None) or []
        if not seg_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no segmentation",
            )
        seg = seg_rows[0]

        m_resp = (
            supabase.table("lesson_materials")
            .select("id,filename,uploaded_at")
            .eq("unit_id", str(unit_id))
            .order("uploaded_at")
            .execute()
        )
        materials = getattr(m_resp, "data", None) or []
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("segmentation_lookup_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="segmentation lookup failed",
        ) from e

    proposed = seg.get("proposed") or {}
    comprehension = seg.get("comprehension") or {}
    excluded = [
        {
            "material_idx": p.get("material_idx"),
            "page_idx": p.get("page_idx"),
            "reason": p.get("reason"),
        }
        for p in (comprehension.get("pages") or [])
        if isinstance(p, dict) and p.get("teach") is False
    ]

    return {
        "status": seg.get("status"),
        "topics": proposed.get("topics") or [],
        "excluded": excluded,
        "materials": [
            {"idx": i, "filename": m.get("filename")}
            for i, m in enumerate(materials)
        ],
        "empty_reason": proposed.get("empty_reason"),
    }


@router.post("/units/{unit_id}/topics")
async def confirm_unit_topics(
    unit_id: UUID,
    body: ConfirmTopicsRequest,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Confirm a unit's (edited) breakdown — materialise `topics` (`§5.7`/`§10`).

    Teacher/admin-gated; the unit's course must be owned by the caller (or
    caller is admin) else 404. Writes the teacher's edited `topics` onto the
    latest `unit_segmentations` row (`status='confirmed'`), then calls
    `confirm_breakdown` — which reads that row back and upserts `topics` +
    `topic_pages`. No segmentation row -> 404. A `ConfirmError` (e.g. an
    empty breakdown) -> 400. Idempotent: a re-confirm updates rather than
    duplicates. Returns `{topic_ids, created, updated, page_count}`.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_unit(supabase, str(unit_id), caller_id)

    try:
        s_resp = (
            supabase.table("unit_segmentations")
            .select("id,proposed,created_at")
            .eq("unit_id", str(unit_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        seg_rows = getattr(s_resp, "data", None) or []
        if not seg_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no segmentation",
            )
        seg = seg_rows[0]

        existing_proposed = seg.get("proposed") or {}
        (
            supabase.table("unit_segmentations")
            .update(
                {
                    "proposed": {
                        **existing_proposed,
                        "topics": [t.model_dump() for t in body.topics],
                    },
                    "status": "confirmed",
                }
            )
            .eq("id", str(seg["id"]))
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("topics_confirm_update_failed", error=str(e), unit_id=str(unit_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="segmentation update failed",
        ) from e

    try:
        result = await confirm_breakdown(str(unit_id))
    except ConfirmError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {
        "topic_ids": result.topic_ids,
        "created": result.created,
        "updated": result.updated,
        "page_count": result.page_count,
    }


# ─── topic / lesson authoring (`/teach/.../topics/[id]`, `teacher-authoring.md`
# §4/§6/§10) ─────────────────────────────────────────────────────────────────
@router.get("/topics/{topic_id}")
async def get_topic_detail(
    topic_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return a topic's lesson, versions + its latest generate job (`§6`/`§10`).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. `versions` is the topic's `topic_versions`
    rows newest-first, each carrying its per-version `validation` result and
    an `active` flag (the row whose id is `topics.active_version_id`).
    `generate_job` is the topic's most recent `kind='generate'`
    `pipeline_jobs` row (shaped `{id,status,stage}`) so the topic screen can
    show / poll generation progress — `null` when never generated.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    topic, unit, course = _load_owned_topic(supabase, str(topic_id), caller_id)

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,label,validation,created_at")
            .eq("topic_id", str(topic_id))
            .order("created_at", desc=True)
            .execute()
        )
        versions = getattr(v_resp, "data", None) or []

        j_resp = (
            supabase.table("pipeline_jobs")
            .select("id,status,stage")
            .eq("topic_id", str(topic_id))
            .eq("kind", "generate")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        job_rows = getattr(j_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("topic_detail_failed", error=str(e), topic_id=str(topic_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic detail lookup failed",
        ) from e

    active_version_id = topic.get("active_version_id")
    generate_job = (
        {
            "id": str(job_rows[0]["id"]),
            "status": job_rows[0].get("status"),
            "stage": job_rows[0].get("stage"),
        }
        if job_rows
        else None
    )

    return {
        "id": str(topic["id"]),
        "name": topic.get("name"),
        "status": topic.get("status"),
        "design_notes": topic.get("design_notes"),
        "content": topic.get("content") or [],
        "active_version_id": active_version_id,
        "course_id": str(course["id"]),
        "unit_id": str(unit["id"]),
        "unit_name": unit.get("name"),
        "generate_job": generate_job,
        "versions": [
            {
                "id": str(v["id"]),
                "label": v.get("label"),
                "created_at": v.get("created_at"),
                "active": str(v["id"]) == str(active_version_id)
                if active_version_id
                else False,
                "validation": v.get("validation"),
            }
            for v in versions
        ],
    }


@router.patch("/topics/{topic_id}")
async def update_topic(
    topic_id: UUID,
    body: TopicUpdate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Update a topic's `design_notes` and / or hand-edited `content` (`§6`).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. A `None` field is left unchanged. A `content`
    edit also mirrors into the ACTIVE `topic_versions` row's `content` when
    the topic has one — a hand-edit mutates the active version in place (the
    §4 invariant `topics.content == active version's content`).
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    topic, _unit, _course = _load_owned_topic(supabase, str(topic_id), caller_id)

    try:
        if body.design_notes is not None:
            (
                supabase.table("topics")
                .update({"design_notes": body.design_notes})
                .eq("id", str(topic_id))
                .execute()
            )
        if body.content is not None:
            (
                supabase.table("topics")
                .update({"content": body.content})
                .eq("id", str(topic_id))
                .execute()
            )
            active_version_id = topic.get("active_version_id")
            if active_version_id:
                (
                    supabase.table("topic_versions")
                    .update({"content": body.content})
                    .eq("id", str(active_version_id))
                    .execute()
                )
    except Exception as e:  # noqa: BLE001
        log.warning("topic_update_failed", error=str(e), topic_id=str(topic_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic update failed",
        ) from e

    return {"ok": True}


@router.post("/topics/{topic_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_topic_endpoint(
    topic_id: UUID,
    background: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Enqueue a `generate` pipeline job for a topic (`§6`/`§10`).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. At most one generate job runs per topic at a
    time: if a `queued` or `running` generate job already exists it is
    returned as-is, without starting another (§13). Otherwise a
    `pipeline_jobs` row is inserted and `run_job` walks it (render -> generate
    + validate) in the background. Returns `{job_id, status}` with HTTP 202.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_topic(supabase, str(topic_id), caller_id)

    try:
        # §13 — at most one in-flight generate job per topic. Return any
        # existing queued/running job instead of starting a second.
        inflight_resp = (
            supabase.table("pipeline_jobs")
            .select("id,status,stage,kind")
            .eq("topic_id", str(topic_id))
            .eq("kind", "generate")
            .in_("status", ["queued", "running"])
            .execute()
        )
        inflight = getattr(inflight_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "generate_job_lookup_failed", error=str(e), topic_id=str(topic_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="generate job lookup failed",
        ) from e

    if inflight:
        existing = inflight[0]
        return {"job_id": str(existing["id"]), "status": existing.get("status")}

    try:
        await ingest_acquire(caller_id)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("pipeline_jobs").insert(
            {
                "id": job_id,
                "kind": "generate",
                "topic_id": str(topic_id),
                "status": "queued",
                "stage": None,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "generate_job_insert_failed", error=str(e), topic_id=str(topic_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="generate job create failed",
        ) from e

    background.add_task(run_job, job_id, handlers=_GENERATE_HANDLERS)
    return {"job_id": job_id, "status": "queued"}


@router.post("/topics/{topic_id}/versions/{version_id}/activate")
async def activate_topic_version(
    topic_id: UUID,
    version_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Make a `topic_versions` row the topic's active version (`§4`/`§6`).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. The version must exist AND belong to this
    topic (else 404). Sets `topics.active_version_id` and mirrors that
    version's `content` into `topics.content` — the §4 invariant.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_topic(supabase, str(topic_id), caller_id)

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,topic_id,content")
            .eq("id", str(version_id))
            .limit(1)
            .execute()
        )
        v_rows = getattr(v_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "topic_version_lookup_failed", error=str(e), version_id=str(version_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic version lookup failed",
        ) from e

    if not v_rows or str(v_rows[0].get("topic_id")) != str(topic_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="version not found"
        )
    version = v_rows[0]

    try:
        (
            supabase.table("topics")
            .update(
                {
                    "active_version_id": str(version_id),
                    "content": version.get("content") or [],
                }
            )
            .eq("id", str(topic_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "topic_version_activate_failed", error=str(e), topic_id=str(topic_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="version activate failed",
        ) from e

    return {"ok": True}


@router.delete(
    "/topics/{topic_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_topic_version(
    topic_id: UUID,
    version_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> None:
    """Delete a non-active `topic_versions` row (`§6`).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. The ACTIVE version cannot be deleted (400 — it
    is the live lesson). The version must belong to this topic (else 404).
    Returns HTTP 204.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    topic, _unit, _course = _load_owned_topic(supabase, str(topic_id), caller_id)

    if str(topic.get("active_version_id") or "") == str(version_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete the active version",
        )

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,topic_id")
            .eq("id", str(version_id))
            .limit(1)
            .execute()
        )
        v_rows = getattr(v_resp, "data", None) or []
        if not v_rows or str(v_rows[0].get("topic_id")) != str(topic_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="version not found",
            )
        (
            supabase.table("topic_versions")
            .delete()
            .eq("id", str(version_id))
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning(
            "topic_version_delete_failed", error=str(e), version_id=str(version_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="version delete failed",
        ) from e
    return None


@router.get("/topics/{topic_id}/versions/{version_id}")
async def get_topic_version(
    topic_id: UUID,
    version_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Return one `topic_versions` row with its full `content` (task 5.1).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. The version must belong to this topic (else
    404). Used by the topic page's version-diff view, which fetches an
    older version's steps to compare against the live lesson.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_topic(supabase, str(topic_id), caller_id)

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,topic_id,label,content,created_at")
            .eq("id", str(version_id))
            .limit(1)
            .execute()
        )
        v_rows = getattr(v_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "topic_version_get_failed", error=str(e), version_id=str(version_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic version lookup failed",
        ) from e

    if not v_rows or str(v_rows[0].get("topic_id")) != str(topic_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="version not found"
        )
    v = v_rows[0]
    return {
        "id": str(v["id"]),
        "label": v.get("label"),
        "content": v.get("content") or [],
        "created_at": v.get("created_at"),
    }


@router.patch("/topics/{topic_id}/versions/{version_id}")
async def update_topic_version_label(
    topic_id: UUID,
    version_id: UUID,
    body: VersionLabelUpdate,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Rename a `topic_versions` row — the teacher's own label (task 5.1).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. The version must belong to this topic (else
    404). Only `label` is editable — a version's `content` is immutable.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_topic(supabase, str(topic_id), caller_id)

    label = body.label.strip()
    if not label:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="label cannot be blank",
        )

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,topic_id")
            .eq("id", str(version_id))
            .limit(1)
            .execute()
        )
        v_rows = getattr(v_resp, "data", None) or []
        if not v_rows or str(v_rows[0].get("topic_id")) != str(topic_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="version not found"
            )
        upd = (
            supabase.table("topic_versions")
            .update({"label": label})
            .eq("id", str(version_id))
            .execute()
        )
        rows = getattr(upd, "data", None) or []
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning(
            "topic_version_label_failed", error=str(e), version_id=str(version_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="version label update failed",
        ) from e

    return {"id": str(version_id), "label": rows[0].get("label") if rows else label}


@router.post("/topics/{topic_id}/publish")
async def publish_topic(
    topic_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Publish a topic — the §6 publish gate (`teacher-authoring.md` §6).

    Teacher/admin-gated; the topic's course must be owned by the caller (or
    caller is admin) else 404. Publish is BLOCKED until the topic's active
    version has validated: the topic must have an `active_version_id` (else
    400) and that version's `validation` must be a dict with `passed is True`
    (else 400). When the gate passes, `topics.status` is set to `published`.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="topic not found"
        )

    caller_id = str(user.get("sub") or "")
    topic, _unit, _course = _load_owned_topic(supabase, str(topic_id), caller_id)

    active_version_id = topic.get("active_version_id")
    if not active_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="generate a lesson first",
        )

    try:
        v_resp = (
            supabase.table("topic_versions")
            .select("id,validation")
            .eq("id", str(active_version_id))
            .limit(1)
            .execute()
        )
        v_rows = getattr(v_resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning(
            "publish_version_lookup_failed", error=str(e), topic_id=str(topic_id)
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic version lookup failed",
        ) from e

    validation = v_rows[0].get("validation") if v_rows else None
    if not (isinstance(validation, dict) and validation.get("passed") is True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lesson has not validated — re-generate to fix the gaps",
        )

    try:
        (
            supabase.table("topics")
            .update({"status": "published"})
            .eq("id", str(topic_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning("topic_publish_failed", error=str(e), topic_id=str(topic_id))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="topic publish failed",
        ) from e

    return {"id": str(topic_id), "status": "published"}


# ─── class ↔ course assignment (`/teach/classes/[id]`, `teacher-authoring.md`
# §5/§9/§10) ──────────────────────────────────────────────────────────────────
@router.post("/classes/{class_id}/courses", status_code=status.HTTP_201_CREATED)
async def assign_class_course(
    class_id: UUID,
    body: ClassCourseAssign,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> dict[str, Any]:
    """Assign one of the caller's courses to one of their classes (`§5`/`§10`).

    Teacher/admin-gated. BOTH the class and the course must be owned by the
    caller (or caller is admin) — `_load_owned_class` / `_load_owned_course`
    each 404 a missing or non-owned resource. Inserts a `class_courses` row;
    idempotent — re-assigning an already-assigned course is a no-op. The
    `class_courses` link is what makes a teacher course visible to the
    class's students (`GET /v1/me/courses`, task 4.1).
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_class(supabase, str(class_id), caller_id)
    course = _load_owned_course(supabase, str(body.course_id), caller_id)

    try:
        existing = (
            supabase.table("class_courses")
            .select("class_id,course_id")
            .eq("class_id", str(class_id))
            .eq("course_id", str(body.course_id))
            .limit(1)
            .execute()
        )
        if not (getattr(existing, "data", None) or []):
            supabase.table("class_courses").insert(
                {
                    "class_id": str(class_id),
                    "course_id": str(body.course_id),
                    "assigned_at": datetime.now(timezone.utc).isoformat(),
                }
            ).execute()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "class_course_assign_failed",
            error=str(e),
            class_id=str(class_id),
            course_id=str(body.course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course assign failed",
        ) from e

    return {"id": str(course["id"]), "title": course.get("title")}


@router.delete(
    "/classes/{class_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_class_course(
    class_id: UUID,
    course_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("teacher", "admin"))],
) -> None:
    """Remove a course assignment from a class (`§9`/`§10`).

    Teacher/admin-gated; the class must be owned by the caller (or caller is
    admin) else 404. Deletes the `class_courses` row keyed
    (class_id, course_id) — the class's students stop seeing that course.
    Returns HTTP 204.
    """
    supabase = get_supabase()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="class not found"
        )

    caller_id = str(user.get("sub") or "")
    _load_owned_class(supabase, str(class_id), caller_id)

    try:
        (
            supabase.table("class_courses")
            .delete()
            .eq("class_id", str(class_id))
            .eq("course_id", str(course_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "class_course_unassign_failed",
            error=str(e),
            class_id=str(class_id),
            course_id=str(course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="course unassign failed",
        ) from e
    return None
