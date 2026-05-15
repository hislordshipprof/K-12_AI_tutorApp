"""Courses & topics endpoints — backed by Supabase.

Falls back to deterministic sample data when Supabase is unreachable
(local dev without `supabase start`). The fallback is gated on the
DEV_MODE flag — in production a Supabase outage will surface as 503.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import CourseOut, TopicOut

router = APIRouter(tags=["courses"])
log = get_logger(__name__)


# ─── Sample data (dev-mode fallback only) ──────────────────────────────────
def _det_uuid(seed: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"k12-tutor::{seed}")


_NOW = datetime.now(timezone.utc)


_SAMPLE_COURSES: list[dict[str, Any]] = [
    {
        "id": _det_uuid("course/physics-1"),
        "slug": "ap-physics-1",
        "title": "AP Physics 1",
        "exam": "AP",
        "color_gradient": "from-sky-400 to-indigo-500",
        "icon_emoji": "⚛️",
        "sort_order": 0,
        "created_at": _NOW,
    },
    {
        "id": _det_uuid("course/algebra-2"),
        "slug": "algebra-2",
        "title": "Algebra II",
        "exam": None,
        "color_gradient": "from-emerald-400 to-teal-500",
        "icon_emoji": "📐",
        "sort_order": 1,
        "created_at": _NOW,
    },
    {
        "id": _det_uuid("course/biology"),
        "slug": "ap-biology",
        "title": "AP Biology",
        "exam": "AP",
        "color_gradient": "from-rose-400 to-pink-500",
        "icon_emoji": "🧬",
        "sort_order": 2,
        "created_at": _NOW,
    },
]


_SAMPLE_TOPICS: dict[UUID, dict[str, Any]] = {
    _det_uuid("topic/kinematics-1d"): {
        "id": _det_uuid("topic/kinematics-1d"),
        "unit_id": _det_uuid("unit/physics-1/mechanics"),
        "n": 1,
        "name": "Kinematics in One Dimension",
        "duration_min": 25,
        "summary": "Position, velocity, acceleration, and the SUVAT equations.",
        "content": [
            {"tts": "Welcome — today we explore motion in one dimension.", "dur": 8},
            {"tts": "We'll define velocity as the rate of change of position.", "dur": 10},
        ],
        "sort_order": 0,
        "created_at": _NOW,
    }
}


# ─── Endpoints ────────────────────────────────────────────────────────────
@router.get("/courses", response_model=list[CourseOut])
async def list_courses() -> list[dict[str, Any]]:
    """Public — drives the landing-page course picker."""
    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("courses")
                .select("*")
                .order("sort_order")
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows
        except Exception as e:  # noqa: BLE001
            log.warning("courses_supabase_failed", error=str(e))
            if not supabase_enabled():
                pass  # already gated
            else:
                # Real outage in non-dev: bubble up.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="courses unavailable",
                ) from e
    # Dev fallback.
    return _SAMPLE_COURSES


@router.get("/topics/{topic_id}")
async def get_topic(
    topic_id: str,
) -> dict[str, Any]:
    """Public-read topic metadata + lesson content for the classroom page.

    Accepts a UUID (real DB topic) or a free-form slug (back-compat with
    the prototype's `wave-properties-anatomy` fixture). Topic data is
    already public-read at the RLS layer, so leaving this unauthenticated
    lets Next's SSR fetch this without plumbing the user JWT through.

    Returns a derived stub when the lookup fails so the classroom page
    still renders rather than 404'ing mid-navigation.

    Shape:
        {
          "id": "<uuid>" | null,
          "slug": "<route param>",
          "name": "Oscillations: Amplitude, Period & Frequency",
          "unit_n": 7,
          "unit_name": "Oscillations",
          "course_slug": "ap-physics-1",
          "has_content": true,
          "content": [{"tts": "...", "html": "...", "dur": "00:00"}, ...] | null,
        }
    """
    # UUID-style params get a clean "Lesson" placeholder; slugs get
    # titlecased while we resolve.
    try:
        UUID(topic_id)
        is_uuid = True
        fallback_name = "Lesson"
    except (ValueError, AttributeError):
        is_uuid = False
        fallback_name = topic_id.replace("-", " ").title()

    fallback: dict[str, Any] = {
        "id": None,
        "slug": topic_id,
        "name": fallback_name,
        "unit_n": None,
        "unit_name": "Unit",
        "course_slug": None,
        "has_content": False,
        "content": None,
    }

    supabase = get_supabase()
    if supabase is None or not is_uuid:
        return fallback

    try:
        t_resp = (
            supabase.table("topics")
            .select("id, n, name, unit_id, content")
            .eq("id", topic_id)
            .limit(1)
            .execute()
        )
        rows = getattr(t_resp, "data", None) or []
        if not rows:
            return fallback
        row = rows[0]

        u_resp = (
            supabase.table("units")
            .select("n, name, course_id")
            .eq("id", row["unit_id"])
            .limit(1)
            .execute()
        )
        u_rows = getattr(u_resp, "data", None) or []
        unit = u_rows[0] if u_rows else {}

        course_slug: str | None = None
        if unit.get("course_id"):
            c_resp = (
                supabase.table("courses")
                .select("slug")
                .eq("id", unit["course_id"])
                .limit(1)
                .execute()
            )
            c_rows = getattr(c_resp, "data", None) or []
            if c_rows:
                course_slug = c_rows[0].get("slug")

        content = row.get("content")
        has_content = bool(
            content
            and (not isinstance(content, str) or content not in ("", "null", "{}"))
        )

        return {
            "id": str(row["id"]),
            "slug": str(row["id"]),
            "name": row["name"],
            "unit_n": unit.get("n"),
            "unit_name": unit.get("name") or "Unit",
            "course_slug": course_slug,
            "has_content": has_content,
            "content": content if has_content else None,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("topic_details_supabase_failed", error=str(e), topic=topic_id)
        return fallback


# ─── Curriculum tree ──────────────────────────────────────────────────────
@router.get("/courses/{slug}/units")
async def list_course_units(
    slug: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Nested unit/topic tree for a course — drives the dashboard curriculum view.

    Returns:
        [
          {
            "id": "<unit uuid>",
            "n": 1,
            "name": "Kinematics",
            "topics": [
              {"id": "<topic uuid>", "n": 1, "name": "...", "duration_min": 12}
            ]
          },
          ...
        ]

    No fake data — when Supabase isn't reachable we return an empty list and
    the frontend renders an "Enroll to see your curriculum" empty state.
    """
    supabase = get_supabase()
    if supabase is None:
        return []

    try:
        # 1. Resolve course slug -> id.
        c_resp = (
            supabase.table("courses")
            .select("id")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        c_rows = getattr(c_resp, "data", None) or []
        if not c_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )
        course_id = c_rows[0]["id"]

        # 2. Units for the course.
        u_resp = (
            supabase.table("units")
            .select("id,n,name")
            .eq("course_id", course_id)
            .order("n")
            .execute()
        )
        units = getattr(u_resp, "data", None) or []
        if not units:
            return []

        # 3. Topics for those units, bulk-fetch and group.
        unit_ids = [u["id"] for u in units]
        t_resp = (
            supabase.table("topics")
            .select("id,unit_id,n,name,duration_min")
            .in_("unit_id", unit_ids)
            .order("n")
            .execute()
        )
        topics_by_unit: dict[str, list[dict[str, Any]]] = {}
        for t in (getattr(t_resp, "data", None) or []):
            topics_by_unit.setdefault(str(t["unit_id"]), []).append(
                {
                    "id": t["id"],
                    "n": t["n"],
                    "name": t["name"],
                    "duration_min": t.get("duration_min"),
                }
            )
        return [
            {
                "id": u["id"],
                "n": u["n"],
                "name": u["name"],
                "topics": topics_by_unit.get(str(u["id"]), []),
            }
            for u in units
        ]
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("course_units_supabase_failed", error=str(e), slug=slug)
        return []


