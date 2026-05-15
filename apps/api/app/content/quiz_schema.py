"""Pydantic schemas for quiz-question generation (Q2).

`QuizSet` is what `gemini-pro-latest` emits via structured output and what
`quiz_persister.persist_quiz_set` writes to `quiz_questions`. Each item
maps 1:1 to a `quiz_questions` row.

Kept separate from `schema.py` (lesson content) so the validator gates can
evolve independently — quiz questions need answer-key sanity checks that
don't apply to lessons.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class QuizQuestion(BaseModel):
    """One multiple-choice question — 4 choices, exactly one correct."""

    prompt: str = Field(
        ...,
        min_length=20,
        max_length=240,
        description=(
            "The question prompt. Plain prose. Math inside $...$ or $$...$$ "
            "LaTeX delimiters."
        ),
    )
    choices: list[str] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Exactly 4 distinct answer choices.",
    )
    correct_idx: int = Field(
        ...,
        ge=0,
        le=3,
        description="0-indexed position of the correct choice within `choices`.",
    )
    explanation: str = Field(
        ...,
        min_length=20,
        max_length=400,
        description=(
            "1-2 sentence explanation of why the correct answer is correct. "
            "Aria's voice. Shown after the student reveals."
        ),
    )

    @field_validator("choices")
    @classmethod
    def _choices_non_empty_and_distinct(cls, v: list[str]) -> list[str]:
        cleaned = [c.strip() for c in v]
        if any(not c for c in cleaned):
            raise ValueError("choices contain empty string")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("choices must be distinct")
        return cleaned


class QuizSet(BaseModel):
    """Top-level container — exactly N questions for one topic."""

    items: list[QuizQuestion] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Exactly 3 quiz questions, varying difficulty.",
    )


__all__ = ["QuizQuestion", "QuizSet"]
