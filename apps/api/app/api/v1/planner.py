"""Weekly study planner — stubs.

The real implementation will run a LangGraph planner agent that proposes
study blocks given the student's enrollments, recent progress, and goal.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.schemas import PlannerRegenerateRequest, PlannerWeekOut, ScheduleBlockOut

router = APIRouter(tags=["planner"])


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    # Treat Monday as the start of the week.
    return d - timedelta(days=d.weekday())


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


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


@router.get("/planner/week", response_model=PlannerWeekOut)
async def get_week(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> PlannerWeekOut:
    start = _week_start()
    return PlannerWeekOut(week_start=start, blocks=_stub_blocks(_user_uuid(user), start))


@router.post("/planner/regenerate", response_model=PlannerWeekOut)
async def regenerate(
    body: PlannerRegenerateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> PlannerWeekOut:
    start = body.week_start or _week_start()
    return PlannerWeekOut(week_start=start, blocks=_stub_blocks(_user_uuid(user), start))
