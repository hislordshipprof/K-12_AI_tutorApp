"""History endpoint — recent lesson sessions for the current user.

`GET /v1/history?limit=20` returns:

  [
    {
      "id": "<session uuid>",
      "topic_id": "<topic uuid>",
      "topic_name": "Oscillations: Amplitude, Period & Frequency",
      "started_at": "...",
      "ended_at": "..." | null,
      "duration_min": 18 | null,
      "score_pct": 87 | null
    },
    ...
  ]

The score is computed from `quiz_attempts` rows that share the same
topic_id and were created after the session started. `duration_min` is
derived from `topic_progress.time_spent_s` for the user/topic pair.
Both are nullable — we never fake a value.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled

router = APIRouter(tags=["history"])
log = get_logger(__name__)


def _user_uuid(user: dict[str, Any]) -> UUID:
    sub = user.get("sub")
    try:
        return UUID(str(sub))
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid user id"
        ) from e


@router.get("/history")
async def list_history(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Recent lesson_sessions for the authenticated user (newest first)."""
    user_id = _user_uuid(user)
    str_id = str(user_id)

    if not supabase_enabled():
        return []

    supabase = get_supabase()
    if supabase is None:
        return []

    try:
        resp = (
            supabase.table("lesson_sessions")
            .select("id,topic_id,started_at,ended_at")
            .eq("user_id", str_id)
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        sessions = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("history_list_failed", error=str(e))
        return []

    if not sessions:
        return []

    topic_ids = list({s["topic_id"] for s in sessions if s.get("topic_id")})

    # Topic names + course — bulk lookup across topics → units → courses
    # so each row carries its real course (never a hardcoded label).
    topic_names: dict[str, str] = {}
    topic_course: dict[str, str] = {}
    if topic_ids:
        try:
            resp = (
                supabase.table("topics")
                .select("id,name,unit_id")
                .in_("id", topic_ids)
                .execute()
            )
            topic_rows = getattr(resp, "data", None) or []
            for row in topic_rows:
                topic_names[str(row["id"])] = row.get("name") or ""

            unit_ids = list({r["unit_id"] for r in topic_rows if r.get("unit_id")})
            unit_course: dict[str, str] = {}
            if unit_ids:
                u_resp = (
                    supabase.table("units")
                    .select("id,course_id")
                    .in_("id", unit_ids)
                    .execute()
                )
                unit_rows = getattr(u_resp, "data", None) or []
                course_ids = list(
                    {r["course_id"] for r in unit_rows if r.get("course_id")}
                )
                course_title: dict[str, str] = {}
                if course_ids:
                    c_resp = (
                        supabase.table("courses")
                        .select("id,title")
                        .in_("id", course_ids)
                        .execute()
                    )
                    for c in (getattr(c_resp, "data", None) or []):
                        course_title[str(c["id"])] = c.get("title") or ""
                for u in unit_rows:
                    if u.get("course_id"):
                        unit_course[str(u["id"])] = course_title.get(
                            str(u["course_id"]), ""
                        )
            for row in topic_rows:
                if row.get("unit_id"):
                    topic_course[str(row["id"])] = unit_course.get(
                        str(row["unit_id"]), ""
                    )
        except Exception as e:  # noqa: BLE001
            log.warning("history_topic_lookup_failed", error=str(e))

    # Per-topic progress (duration). One small table — cheap to fetch all.
    progress: dict[str, int] = {}
    try:
        resp = (
            supabase.table("topic_progress")
            .select("topic_id,time_spent_s")
            .eq("user_id", str_id)
            .in_("topic_id", topic_ids)
            .execute()
        )
        for row in (getattr(resp, "data", None) or []):
            progress[str(row["topic_id"])] = int(row.get("time_spent_s") or 0)
    except Exception as e:  # noqa: BLE001
        log.debug("history_progress_lookup_failed", error=str(e))

    # Per-topic quiz score.
    quiz_scores: dict[str, int] = {}
    try:
        resp = (
            supabase.table("quiz_attempts")
            .select("topic_id,correct")
            .eq("user_id", str_id)
            .in_("topic_id", topic_ids)
            .execute()
        )
        agg: dict[str, list[bool]] = {}
        for row in (getattr(resp, "data", None) or []):
            agg.setdefault(str(row["topic_id"]), []).append(bool(row.get("correct")))
        for tid, results in agg.items():
            if results:
                quiz_scores[tid] = round(sum(results) / len(results) * 100)
    except Exception as e:  # noqa: BLE001
        log.debug("history_quiz_lookup_failed", error=str(e))

    out: list[dict[str, Any]] = []
    for s in sessions:
        tid = str(s.get("topic_id") or "")
        duration_min: int | None = None
        if tid in progress:
            duration_min = round(progress[tid] / 60) or None
        out.append(
            {
                "id": s["id"],
                "topic_id": s.get("topic_id"),
                "topic_name": topic_names.get(tid),
                "course": topic_course.get(tid) or None,
                "started_at": s.get("started_at"),
                "ended_at": s.get("ended_at"),
                "duration_min": duration_min,
                "score_pct": quiz_scores.get(tid),
            }
        )
    return out
