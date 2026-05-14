"""Quiz endpoints — stubs. Question generation will move to LangGraph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.schemas import QuizAttemptIn, QuizAttemptOut, QuizQuestion

router = APIRouter(tags=["quiz"])


_SAMPLE_QUESTION = QuizQuestion(
    idx=0,
    prompt="A car accelerates uniformly from rest at 2 m/s². "
    "How far has it travelled after 5 seconds?",
    choices=["10 m", "20 m", "25 m", "50 m"],
    correct_idx=2,  # included server-side; stripped before sending to client below
    explanation="Use s = ½at² → ½ × 2 × 25 = 25 m.",
)


@router.get("/quiz/{topic_id}", response_model=QuizQuestion)
async def get_quiz_question(
    topic_id: UUID,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> QuizQuestion:
    """Generate (or fetch) a quiz question for a topic.

    For the stub: returns a fixed question with `correct_idx` *withheld*
    so the client can't peek.
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
    """Score an attempt and return the result + explanation."""
    correct = attempt.picked_idx == _SAMPLE_QUESTION.correct_idx
    user_id_str = user.get("sub", str(uuid4()))
    try:
        user_id = UUID(str(user_id_str))
    except ValueError:
        user_id = uuid4()
    return {
        "id": uuid4(),
        "user_id": user_id,
        "topic_id": topic_id,
        "question_idx": attempt.question_idx,
        "picked_idx": attempt.picked_idx,
        "correct": correct,
        "created_at": datetime.now(timezone.utc),
    }
