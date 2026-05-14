"""Quiz endpoints — questions still stubbed; attempts persist to Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import QuizAttemptIn, QuizAttemptOut, QuizQuestion

router = APIRouter(tags=["quiz"])
log = get_logger(__name__)


_SAMPLE_QUESTION = QuizQuestion(
    idx=0,
    prompt="A car accelerates uniformly from rest at 2 m/s². "
    "How far has it travelled after 5 seconds?",
    choices=["10 m", "20 m", "25 m", "50 m"],
    correct_idx=2,
    explanation="Use s = ½at² → ½ × 2 × 25 = 25 m.",
)


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


@router.get("/quiz/{topic_id}", response_model=QuizQuestion)
async def get_quiz_question(
    topic_id: UUID,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> QuizQuestion:
    """Generate / fetch a quiz question for a topic.

    Question generation will move to LangGraph in a later phase; for now
    we return the seeded sample question with ``correct_idx`` withheld.
    """
    return QuizQuestion(
        idx=_SAMPLE_QUESTION.idx,
        prompt=_SAMPLE_QUESTION.prompt,
        choices=list(_SAMPLE_QUESTION.choices),
        correct_idx=None,
        explanation=None,
    )


@router.post("/quiz/{topic_id}/attempt", response_model=QuizAttemptOut)
async def submit_attempt(
    topic_id: UUID,
    attempt: QuizAttemptIn,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Score an attempt and persist to ``quiz_attempts``."""
    correct = attempt.picked_idx == _SAMPLE_QUESTION.correct_idx
    user_id = _user_uuid(user)

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("quiz_attempts")
                .insert(
                    {
                        "user_id": str(user_id),
                        "topic_id": str(topic_id),
                        "question_idx": attempt.question_idx,
                        "picked_idx": attempt.picked_idx,
                        "correct": correct,
                    }
                )
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise RuntimeError("insert returned no rows")
        except Exception as e:  # noqa: BLE001
            log.warning("quiz_attempt_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="quiz attempt unavailable",
                ) from e

    return {
        "id": uuid4(),
        "user_id": user_id,
        "topic_id": topic_id,
        "question_idx": attempt.question_idx,
        "picked_idx": attempt.picked_idx,
        "correct": correct,
        "created_at": datetime.now(timezone.utc),
    }
