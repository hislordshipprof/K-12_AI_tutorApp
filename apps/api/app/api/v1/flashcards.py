"""Flashcards endpoints — Supabase-backed with SM-2 scheduling.

Real spaced-repetition algorithm: SM-2 (Anki's classic). On review:
  * quality < 3   → ease floors at 1.3, interval resets to 1 day
  * quality >= 3  → ease adjusts via the SM-2 formula, interval grows
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import FlashcardOut, FlashcardReview

router = APIRouter(tags=["flashcards"])
log = get_logger(__name__)


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


def _sm2(current_ease: float, current_interval: int, quality: int) -> tuple[float, int]:
    """SM-2 update — returns (new_ease, new_interval_days)."""
    q = max(0, min(5, quality))
    if q < 3:
        # Failed recall: reset interval, slightly decrease ease.
        new_ease = max(1.3, current_ease - 0.2)
        return new_ease, 1
    # Successful recall.
    new_ease = max(1.3, current_ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    if current_interval <= 1:
        new_interval = 6 if q >= 4 else 1
    else:
        new_interval = max(1, int(round(current_interval * new_ease)))
    return new_ease, new_interval


@router.get("/flashcards/due", response_model=list[FlashcardOut])
async def list_due(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]] | list[FlashcardOut]:
    uid = _user_uuid(user)
    today = date.today()

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("flashcards")
                .select("*")
                .eq("user_id", str(uid))
                .lte("due_at", today.isoformat())
                .order("due_at")
                .execute()
            )
            return getattr(resp, "data", None) or []
        except Exception as e:  # noqa: BLE001
            log.warning("flashcards_due_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="flashcards unavailable",
                ) from e

    return [_sample_card(uid)]


@router.post("/flashcards/{card_id}/review", response_model=FlashcardOut)
async def review_card(
    card_id: UUID,
    body: FlashcardReview,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> FlashcardOut | dict[str, Any]:
    if body.quality < 0 or body.quality > 5:
        raise HTTPException(status_code=400, detail="quality must be 0–5")
    uid = _user_uuid(user)
    now = datetime.now(timezone.utc)

    supabase = get_supabase()
    if supabase is not None:
        try:
            # Load the current card so we can compute the SM-2 update.
            sel = (
                supabase.table("flashcards")
                .select("*")
                .eq("id", str(card_id))
                .eq("user_id", str(uid))
                .limit(1)
                .execute()
            )
            rows = getattr(sel, "data", None) or []
            if not rows:
                raise HTTPException(status_code=404, detail="Card not found")
            current = rows[0]
            new_ease, new_interval = _sm2(
                float(current.get("ease") or 2.5),
                int(current.get("interval_days") or 1),
                body.quality,
            )
            new_due = (date.today() + timedelta(days=new_interval)).isoformat()

            upd = (
                supabase.table("flashcards")
                .update(
                    {
                        "ease": new_ease,
                        "interval_days": new_interval,
                        "due_at": new_due,
                        "last_reviewed_at": now.isoformat(),
                    }
                )
                .eq("id", str(card_id))
                .eq("user_id", str(uid))
                .execute()
            )
            updated = getattr(upd, "data", None) or []
            if updated:
                return updated[0]
            return {**current, "ease": new_ease, "interval_days": new_interval}
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("flashcard_review_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="flashcard review unavailable",
                ) from e

    # Dev fallback — pretend the schedule advanced.
    card = _sample_card(uid)
    card_dict = card.model_dump()
    card_dict["id"] = card_id
    new_ease, new_interval = _sm2(2.5, 1, body.quality)
    card_dict["ease"] = new_ease
    card_dict["interval_days"] = new_interval
    card_dict["last_reviewed_at"] = now
    return FlashcardOut(**card_dict)
