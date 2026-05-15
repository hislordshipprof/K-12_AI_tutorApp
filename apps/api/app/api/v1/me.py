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
