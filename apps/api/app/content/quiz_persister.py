"""Persist a validated ``QuizSet`` to ``quiz_questions`` (Q2).

Idempotency: writes are keyed by ``(topic_id, idx)``. On a re-run we delete
the prior set for the topic then insert fresh — there's no human-review
flow on quizzes yet, so this is simpler than the lesson persister.

Quiz rows DO NOT live on ``topics.content`` — they're a separate table.
That keeps the lesson teleprompter format unaware of quiz state and lets
us regenerate quizzes without touching lessons.
"""

from __future__ import annotations

from typing import Any

from app.content.quiz_schema import QuizSet
from app.core.logging import get_logger

log = get_logger(__name__)


class QuizPersister:
    """Service-role Supabase writer for validated quiz sets."""

    def __init__(self, supabase: Any) -> None:
        if supabase is None:
            raise RuntimeError(
                "QuizPersister requires a Supabase client (service_role)."
            )
        self.sb = supabase

    async def persist(
        self,
        topic_id: str,
        quiz: QuizSet,
        provenance: dict[str, Any],
    ) -> int:
        """Replace the existing question set for ``topic_id`` with ``quiz``.

        Returns the number of rows written.
        """
        # Clear prior rows for this topic — keeps `(topic_id, idx)` unique
        # without us having to upsert one-by-one.
        self.sb.table("quiz_questions").delete().eq(
            "topic_id", topic_id
        ).execute()

        rows = [
            {
                "topic_id": topic_id,
                "idx": i,
                "prompt": q.prompt,
                "choices": q.choices,
                "correct_idx": q.correct_idx,
                "explanation": q.explanation,
                "provenance": provenance,
            }
            for i, q in enumerate(quiz.items)
        ]
        self.sb.table("quiz_questions").insert(rows).execute()
        log.info(
            "quiz_persisted",
            topic_id=topic_id,
            count=len(rows),
        )
        return len(rows)


__all__ = ["QuizPersister"]
