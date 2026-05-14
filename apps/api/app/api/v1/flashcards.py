"""Flashcards endpoints — SM-2 review stub.

Real spaced-repetition scheduling will be wired alongside Supabase persistence.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.models.schemas import FlashcardOut, FlashcardReview

router = APIRouter(tags=["flashcards"])


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


def _sample_card(user_id: UUID) -> FlashcardOut:
    return FlashcardOut(
        id=uuid4(),
        deck_id=uuid4(),
        user_id=user_id,
        front="Define velocity.",
        back="Velocity is the rate of change of position — a vector with magnitude and direction.",
        ease=2.5,
        interval_days=1,
        due_at=date.today(),
        last_reviewed_at=None,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/flashcards/due", response_model=list[FlashcardOut])
async def list_due(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[FlashcardOut]:
    return [_sample_card(_user_uuid(user))]


@router.post("/flashcards/{card_id}/review", response_model=FlashcardOut)
async def review_card(
    card_id: UUID,
    body: FlashcardReview,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> FlashcardOut:
    if body.quality < 0 or body.quality > 5:
        raise HTTPException(status_code=400, detail="quality must be 0–5")
    # Stub: pretend we advanced the schedule.
    card = _sample_card(_user_uuid(user))
    card_dict = card.model_dump()
    card_dict["id"] = card_id
    card_dict["interval_days"] = max(1, body.quality * 2)
    card_dict["last_reviewed_at"] = datetime.now(timezone.utc)
    return FlashcardOut(**card_dict)
