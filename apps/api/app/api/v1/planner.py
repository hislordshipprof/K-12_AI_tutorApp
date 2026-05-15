"""Weekly study planner — Supabase-backed (with dev fallback).

The real LangGraph planner agent will replace ``_stub_blocks`` in a
later phase; for now ``regenerate`` overwrites the user's week with the
stub blocks and returns the new plan.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import (
    PlannerRegenerateRequest,
    PlannerWeekOut,
    ScheduleBlockOut,
)

router = APIRouter(tags=["planner"])
log = get_logger(__name__)


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


def _stub_blocks(user_id: UUID, start: date) -> list[ScheduleBlockOut]:
    now = datetime.now(timezone.utc)
    return [
        ScheduleBlockOut(
            id=uuid4(),
            user_id=user_id,
            date=start + timedelta(days=i),
            start_time=time(16, 0),
            duration_min=30,
            kind="lesson",
            payload={"title": f"Day {i + 1} lesson"},
            status="planned",
            created_at=now,
        )
        for i in range(5)
    ]


def _stub_block_dicts(user_id: UUID, start: date) -> list[dict[str, Any]]:
    """Insert-ready payloads for the planner's stub blocks."""
    return [
        {
            "user_id": str(user_id),
            "date": (start + timedelta(days=i)).isoformat(),
            "start_time": "16:00:00",
            "duration_min": 30,
            "kind": "lesson",
            "payload": {"title": f"Day {i + 1} lesson"},
            "status": "planned",
        }
        for i in range(5)
    ]


@router.get("/planner/week", response_model=PlannerWeekOut)
async def get_week(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    week_start: Annotated[
        date | None,
        Query(description="Monday of the week to fetch; defaults to this week"),
    ] = None,
) -> PlannerWeekOut:
    user_id = _user_uuid(user)
    start = _week_start(week_start)
    week_end = start + timedelta(days=7)

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("schedule_blocks")
                .select("*")
                .eq("user_id", str(user_id))
                .gte("date", start.isoformat())
                .lt("date", week_end.isoformat())
                .order("date")
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            return PlannerWeekOut(week_start=start, blocks=rows)
        except Exception as e:  # noqa: BLE001
            log.warning("planner_week_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="planner unavailable",
                ) from e

    return PlannerWeekOut(week_start=start, blocks=_stub_blocks(user_id, start))


@router.post("/planner/regenerate", response_model=PlannerWeekOut)
async def regenerate(
    body: PlannerRegenerateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> PlannerWeekOut:
    user_id = _user_uuid(user)
    start = body.week_start or _week_start()
    week_end = start + timedelta(days=7)

    supabase = get_supabase()
    if supabase is not None:
        try:
            # Wipe the existing week, then bulk-insert fresh blocks.
            (
                supabase.table("schedule_blocks")
                .delete()
                .eq("user_id", str(user_id))
                .gte("date", start.isoformat())
                .lt("date", week_end.isoformat())
                .execute()
            )
            new_rows = _stub_block_dicts(user_id, start)
            resp = supabase.table("schedule_blocks").insert(new_rows).execute()
            rows = getattr(resp, "data", None) or []
            return PlannerWeekOut(week_start=start, blocks=rows)
        except Exception as e:  # noqa: BLE001
            log.warning("planner_regen_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="planner unavailable",
                ) from e

    return PlannerWeekOut(week_start=start, blocks=_stub_blocks(user_id, start))
