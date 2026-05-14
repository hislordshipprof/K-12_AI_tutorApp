"""Courses & topics endpoints — stubs returning sample data.

A later agent will wire these to Supabase. The shape of the responses
here matches `CourseOut` / `TopicOut` exactly so the frontend can be
built against the real contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid5, NAMESPACE_URL

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import CourseOut, TopicOut

router = APIRouter(tags=["courses"])


# Deterministic UUIDs so the stub data is stable between requests/restarts.
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


@router.get("/courses", response_model=list[CourseOut])
async def list_courses() -> list[dict[str, Any]]:
    """Public — drives the landing-page course picker."""
    return _SAMPLE_COURSES


@router.get("/topics/{topic_id}", response_model=TopicOut)
async def get_topic(
    topic_id: UUID,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Authenticated — full topic content (lesson steps + summary)."""
    topic = _SAMPLE_TOPICS.get(topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        )
    return topic
