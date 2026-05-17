"""Current-user endpoint — profile + lightweight stats for the dashboard.

`GET /v1/me` returns:

  {
    "id": "<uuid>",
    "full_name": "Dev User",
    "avatar_color": "#5B5BE5",
    "streak_days": 0,
    "stats": {
      "topics_done": 0,
      "time_spent_min": 0,
      "quiz_avg_pct": null   // null when the user hasn't attempted any quiz yet
    }
  }

All values are computed from real DB rows. No fixtures.

When Supabase isn't reachable (local-dev placeholder) we return a
minimal profile shell so the dashboard renders an empty state instead
of crashing.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled

router = APIRouter(tags=["me"])
log = get_logger(__name__)


def _user_uuid(user: dict[str, Any]) -> UUID:
    sub = user.get("sub")
    try:
        return UUID(str(sub))
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid user id"
        ) from e


def _empty_profile(user_id: str) -> dict[str, Any]:
    return {
        "id": user_id,
        "full_name": None,
        "avatar_color": "#5B5BE5",
        "streak_days": 0,
        "stats": {
            "topics_done": 0,
            "time_spent_min": 0,
            "quiz_avg_pct": None,
        },
        "last_topic": None,
    }


@router.get("/me")
async def get_me(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Profile + dashboard stats for the current authenticated user."""
    user_id = _user_uuid(user)
    str_id = str(user_id)

    if not supabase_enabled():
        # Local dev without Supabase — return an honest empty shell so the
        # frontend renders the "Sign in / Start your first lesson" empty state.
        return _empty_profile(str_id)

    supabase = get_supabase()
    if supabase is None:
        return _empty_profile(str_id)

    # 1. Profile row (full_name + avatar_color).
    profile: dict[str, Any] = {}
    try:
        resp = (
            supabase.table("profiles")
            .select("full_name,avatar_color,streak_days")
            .eq("id", str_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if rows:
            profile = rows[0]
    except Exception as e:  # noqa: BLE001
        log.warning("me_profile_lookup_failed", error=str(e))

    # 2. Stats: topics done + time spent + quiz avg.
    topics_done = 0
    time_spent_s = 0
    try:
        resp = (
            supabase.table("topic_progress")
            .select("status,time_spent_s")
            .eq("user_id", str_id)
            .execute()
        )
        for row in (getattr(resp, "data", None) or []):
            if row.get("status") == "done":
                topics_done += 1
            time_spent_s += int(row.get("time_spent_s") or 0)
    except Exception as e:  # noqa: BLE001
        log.warning("me_progress_lookup_failed", error=str(e))

    quiz_avg_pct: int | None = None
    try:
        resp = (
            supabase.table("quiz_attempts")
            .select("correct")
            .eq("user_id", str_id)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if rows:
            correct = sum(1 for r in rows if r.get("correct") is True)
            quiz_avg_pct = round((correct / len(rows)) * 100)
    except Exception as e:  # noqa: BLE001
        log.warning("me_quiz_lookup_failed", error=str(e))

    # 3. Streak — DB function `compute_streak(uuid)` (defined in migration
    # 20260514000200_functions). Best-effort; defaults to profile column.
    streak_days = int(profile.get("streak_days") or 0)
    try:
        resp = supabase.rpc("compute_streak", {"p_user_id": str_id}).execute()
        v = getattr(resp, "data", None)
        if isinstance(v, int):
            streak_days = v
        elif isinstance(v, list) and v:
            streak_days = int(v[0]) if isinstance(v[0], int) else streak_days
    except Exception as e:  # noqa: BLE001
        log.debug("me_streak_rpc_failed", error=str(e))

    # 4. Last-active topic — drives the dashboard "Pick up where you left
    # off" hero. We pick the most-recent lesson_sessions row that's still
    # open OR the most recently created, then expand the topic for the
    # title + duration.
    last_topic: dict[str, Any] | None = None
    try:
        sess_resp = (
            supabase.table("lesson_sessions")
            .select("topic_id,started_at,ended_at")
            .eq("user_id", str_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        sess_rows = getattr(sess_resp, "data", None) or []
        if sess_rows and sess_rows[0].get("topic_id"):
            top_id = sess_rows[0]["topic_id"]
            t_resp = (
                supabase.table("topics")
                .select("id,name,duration_min,unit_id")
                .eq("id", top_id)
                .limit(1)
                .execute()
            )
            t_rows = getattr(t_resp, "data", None) or []
            if t_rows:
                t = t_rows[0]
                unit_n: int | None = None
                unit_name: str | None = None
                course_slug: str | None = None
                if t.get("unit_id"):
                    u_resp = (
                        supabase.table("units")
                        .select("n,name,course_id")
                        .eq("id", t["unit_id"])
                        .limit(1)
                        .execute()
                    )
                    u_rows = getattr(u_resp, "data", None) or []
                    if u_rows:
                        unit_n = u_rows[0].get("n")
                        unit_name = u_rows[0].get("name")
                        if u_rows[0].get("course_id"):
                            c_resp = (
                                supabase.table("courses")
                                .select("slug,title")
                                .eq("id", u_rows[0]["course_id"])
                                .limit(1)
                                .execute()
                            )
                            c_rows = getattr(c_resp, "data", None) or []
                            if c_rows:
                                course_slug = c_rows[0].get("slug")
                last_topic = {
                    "id": t["id"],
                    "name": t["name"],
                    "duration_min": t.get("duration_min"),
                    "unit_n": unit_n,
                    "unit_name": unit_name,
                    "course_slug": course_slug,
                }
    except Exception as e:  # noqa: BLE001
        log.warning("me_last_topic_lookup_failed", error=str(e))

    return {
        "id": str_id,
        "full_name": profile.get("full_name"),
        "avatar_color": profile.get("avatar_color") or "#5B5BE5",
        "streak_days": streak_days,
        "stats": {
            "topics_done": topics_done,
            "time_spent_min": round(time_spent_s / 60),
            "quiz_avg_pct": quiz_avg_pct,
        },
        "last_topic": last_topic,
    }


@router.get("/me/courses")
async def list_my_courses(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """The dashboard course list, split into Recommended + teacher courses.

    Each item carries a `group` field — `'recommended'` (the built-in
    OpenStax courses, `origin='recommended'`) or `'teacher'` (a course
    assigned to a class the caller is an **active** member of, reached via
    `class_members` -> `class_courses`, `teacher-authoring.md` §8 / §10).
    A teacher item also carries `published_topic_count` so the dashboard
    can show "coming soon" for an all-draft course; it is `null` on a
    Recommended course (always enterable).

    The service-role client bypasses RLS, so the teacher set is scoped to
    the caller explicitly — only classes the caller actively belongs to.
    """
    supabase = get_supabase()
    if supabase is None:
        return []

    caller_id = str(user.get("sub") or "")
    cols = "id,slug,title,exam,subject,color_gradient,icon_emoji"

    def _item(c: dict[str, Any], group: str, pub: int | None) -> dict[str, Any]:
        return {
            "id": str(c["id"]),
            "slug": c.get("slug"),
            "title": c.get("title"),
            "exam": c.get("exam"),
            "subject": c.get("subject"),
            "color_gradient": c.get("color_gradient"),
            "icon_emoji": c.get("icon_emoji"),
            "group": group,
            "published_topic_count": pub,
        }

    out: list[dict[str, Any]] = []
    try:
        # Recommended — the built-in courses.
        rec_resp = (
            supabase.table("courses")
            .select(cols)
            .eq("origin", "recommended")
            .order("sort_order")
            .execute()
        )
        out.extend(
            _item(c, "recommended", None)
            for c in (getattr(rec_resp, "data", None) or [])
        )

        # Teacher — courses assigned to a class the caller actively belongs to.
        m_resp = (
            supabase.table("class_members")
            .select("class_id,status")
            .eq("student_id", caller_id)
            .eq("status", "active")
            .execute()
        )
        class_ids = [
            str(m["class_id"])
            for m in (getattr(m_resp, "data", None) or [])
            if m.get("class_id")
        ]
        course_ids: list[str] = []
        if class_ids:
            cc_resp = (
                supabase.table("class_courses")
                .select("course_id")
                .in_("class_id", class_ids)
                .execute()
            )
            for r in getattr(cc_resp, "data", None) or []:
                cid = str(r.get("course_id") or "")
                if cid and cid not in course_ids:
                    course_ids.append(cid)

        if course_ids:
            tc_resp = (
                supabase.table("courses").select(cols).in_("id", course_ids).execute()
            )
            teacher_courses = getattr(tc_resp, "data", None) or []

            # published-topic counts: course -> units -> topics(status='published').
            u_resp = (
                supabase.table("units")
                .select("id,course_id")
                .in_("course_id", course_ids)
                .execute()
            )
            units = getattr(u_resp, "data", None) or []
            course_of_unit = {str(u["id"]): str(u["course_id"]) for u in units}
            published: dict[str, int] = {}
            if units:
                t_resp = (
                    supabase.table("topics")
                    .select("unit_id,status")
                    .in_("unit_id", [str(u["id"]) for u in units])
                    .eq("status", "published")
                    .execute()
                )
                for t in getattr(t_resp, "data", None) or []:
                    cid = course_of_unit.get(str(t.get("unit_id")))
                    if cid:
                        published[cid] = published.get(cid, 0) + 1

            out.extend(
                _item(c, "teacher", published.get(str(c["id"]), 0))
                for c in teacher_courses
            )
    except Exception as e:  # noqa: BLE001
        log.warning("me_courses_lookup_failed", error=str(e), user=caller_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="courses lookup failed",
        ) from e

    return out


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> None:
    """Delete the **calling** user's account and all of their personal data.

    Self-service account deletion — the §14 compliance "deletion path".
    This endpoint can only ever delete the caller's own account: the target
    user id is taken from the verified JWT (`sub`), never from the request
    body or a path/query parameter, so there is no way to delete anyone else.

    Removing the `auth.users` row cascades — every table that references the
    user with `on delete cascade` (profiles, lesson_sessions, topic_progress,
    quiz_attempts, notes, flashcards, …) is cleaned up by Postgres. The
    profile row also goes via that cascade.

    Returns 204 on success.
    """
    user_id = _user_uuid(user)
    str_id = str(user_id)

    supabase = get_supabase()
    if supabase is None:
        # No Supabase (local-dev placeholder) — there is no account store to
        # delete from. Report it honestly rather than pretending success.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account deletion unavailable",
        )

    try:
        # Admin API delete of the auth.users row. `on delete cascade` FKs then
        # purge profiles / sessions / progress / quiz attempts / notes / etc.
        supabase.auth.admin.delete_user(str_id)
    except Exception as e:  # noqa: BLE001
        log.warning("account_delete_failed", error=str(e), user_id=str_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account deletion failed",
        ) from e

    log.info("account_deleted", user_id=str_id)
    return None
