"""Quiz endpoints — questions served from ``quiz_questions``, attempts persist."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.session_auth import require_session_owner
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import QuizAttemptIn, QuizAttemptOut, QuizQuestion

router = APIRouter(tags=["quiz"])
log = get_logger(__name__)


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


def _no_questions(topic_id: UUID) -> HTTPException:
    """Raised when a topic has no rows in ``quiz_questions``.

    Uses 404 so the client can render a friendly empty state instead of a
    scary error. The ``code`` payload lets the UI differentiate from a real
    missing-resource 404.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NO_QUESTIONS", "topic_id": str(topic_id)},
    )


@router.get("/quiz/{topic_id}", response_model=QuizQuestion)
async def get_quiz_question(
    topic_id: UUID,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> QuizQuestion:
    """Return a random question from ``quiz_questions`` for this topic.

    `correct_idx` and `explanation` are withheld until the student submits
    an attempt — keeps the student honest in dev tools.
    """
    supabase = get_supabase()
    if supabase is None:
        # No DB wired in this env — the test/dev fallback used to be a
        # hardcoded sample, but a 404-with-code is a more honest signal.
        raise _no_questions(topic_id)

    try:
        resp = (
            supabase.table("quiz_questions")
            .select("idx, prompt, choices")
            .eq("topic_id", str(topic_id))
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning("quiz_fetch_failed", topic_id=str(topic_id), error=str(e))
        if supabase_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="quiz lookup unavailable",
            ) from e
        raise _no_questions(topic_id) from e

    rows = getattr(resp, "data", None) or []
    if not rows:
        raise _no_questions(topic_id)

    row = random.choice(rows)
    return QuizQuestion(
        idx=row["idx"],
        prompt=row["prompt"],
        choices=list(row["choices"]),
        correct_idx=None,
        explanation=None,
    )


@router.post("/quiz/{topic_id}/attempt", response_model=QuizAttemptOut)
async def submit_attempt(
    topic_id: UUID,
    attempt: QuizAttemptIn,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Score against the real answer key and persist to ``quiz_attempts``.

    Response includes `correct_idx` + `explanation` so the client can
    reveal the right answer + Aria's reasoning.
    """
    user_id = _user_uuid(user)
    supabase = get_supabase()

    correct_idx: int | None = None
    explanation: str | None = None

    if supabase is not None:
        try:
            q = (
                supabase.table("quiz_questions")
                .select("correct_idx, explanation")
                .eq("topic_id", str(topic_id))
                .eq("idx", attempt.question_idx)
                .limit(1)
                .execute()
            )
            rows = getattr(q, "data", None) or []
            if rows:
                correct_idx = rows[0].get("correct_idx")
                explanation = rows[0].get("explanation")
        except Exception as e:  # noqa: BLE001
            log.warning(
                "quiz_lookup_failed",
                topic_id=str(topic_id),
                idx=attempt.question_idx,
                error=str(e),
            )

    # If we couldn't resolve the answer key, score as None — UI can fall
    # back to "we couldn't grade this" rather than asserting correctness.
    correct = (
        attempt.picked_idx == correct_idx if correct_idx is not None else None
    )

    if supabase is not None:
        try:
            insert = (
                supabase.table("quiz_attempts")
                .insert(
                    {
                        "user_id": str(user_id),
                        "topic_id": str(topic_id),
                        "question_idx": attempt.question_idx,
                        "picked_idx": attempt.picked_idx,
                        "correct": correct if correct is not None else False,
                    }
                )
                .execute()
            )
            rows = getattr(insert, "data", None) or []
            if rows:
                stored = rows[0]
                return {
                    **stored,
                    "correct_idx": correct_idx,
                    "explanation": explanation,
                }
        except Exception as e:  # noqa: BLE001
            log.warning("quiz_attempt_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="quiz attempt unavailable",
                ) from e

    # In-memory fallback (DEV_MODE / no DB).
    return {
        "id": uuid4(),
        "user_id": user_id,
        "topic_id": topic_id,
        "question_idx": attempt.question_idx,
        "picked_idx": attempt.picked_idx,
        "correct": bool(correct),
        "created_at": datetime.now(timezone.utc),
        "correct_idx": correct_idx,
        "explanation": explanation,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped variants — the classroom only knows `sessionId`, so these
# resolve `topic_id` from `lesson_sessions` before delegating to the
# topic-scoped logic above. Ownership is enforced via `require_session_owner`.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/sessions/{session_id}/quiz", response_model=QuizQuestion)
async def get_quiz_for_session(
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> QuizQuestion:
    topic_id_raw = session.get("topic_id")
    if not topic_id_raw:
        raise _no_questions(UUID(int=0))
    return await get_quiz_question(UUID(str(topic_id_raw)), user)


@router.post(
    "/sessions/{session_id}/quiz/attempt", response_model=QuizAttemptOut
)
async def submit_attempt_for_session(
    attempt: QuizAttemptIn,
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    topic_id_raw = session.get("topic_id")
    if not topic_id_raw:
        raise _no_questions(UUID(int=0))
    return await submit_attempt(UUID(str(topic_id_raw)), attempt, user)
