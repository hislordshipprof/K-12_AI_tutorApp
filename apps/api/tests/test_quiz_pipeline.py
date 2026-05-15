"""Unit tests for the quiz-content pipeline (Q2).

Schema + validator only — the generator is exercised end-to-end by the bulk
run script against real Gemini and doesn't make sense to mock here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.content.quiz_schema import QuizQuestion, QuizSet
from app.content.quiz_validator import validate


# ── schema gates ─────────────────────────────────────────────────────────────
def test_quiz_question_accepts_well_formed_input() -> None:
    q = QuizQuestion(
        prompt="What is the period $T$ when frequency $f$ doubles?",
        choices=["doubles", "halves", "stays the same", "drops to zero"],
        correct_idx=1,
        explanation="Because $T = 1/f$, doubling $f$ halves $T$.",
    )
    assert q.correct_idx == 1


def test_quiz_question_rejects_short_prompt() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="?",
            choices=["a", "b", "c", "d"],
            correct_idx=0,
            explanation="long enough explanation goes here.",
        )


def test_quiz_question_rejects_three_choices() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="A perfectly fine prompt for testing purposes?",
            choices=["a", "b", "c"],
            correct_idx=0,
            explanation="long enough explanation goes here.",
        )


def test_quiz_question_rejects_duplicate_choices() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="A perfectly fine prompt for testing purposes?",
            choices=["same", "same", "different", "another"],
            correct_idx=0,
            explanation="long enough explanation goes here.",
        )


def test_quiz_question_rejects_out_of_range_correct_idx() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            prompt="A perfectly fine prompt for testing purposes?",
            choices=["a", "b", "c", "d"],
            correct_idx=4,
            explanation="long enough explanation goes here.",
        )


def test_quiz_set_requires_exactly_three_questions() -> None:
    q = QuizQuestion(
        prompt="A perfectly fine prompt for testing purposes?",
        choices=["a", "b", "c", "d"],
        correct_idx=0,
        explanation="long enough explanation goes here.",
    )
    # 2 → too few.
    with pytest.raises(ValidationError):
        QuizSet(items=[q, q])
    # 4 → too many.
    with pytest.raises(ValidationError):
        QuizSet(items=[q, q, q, q])
    # 3 → ok.
    QuizSet(items=[q, q, q])


# ── content validator gates ──────────────────────────────────────────────────
def _good_q(prompt: str, **overrides) -> QuizQuestion:
    base = dict(
        prompt=prompt,
        choices=["a thing", "another thing", "third option", "fourth one"],
        correct_idx=0,
        explanation="A plausible explanation that is long enough to pass.",
    )
    base.update(overrides)
    return QuizQuestion(**base)


def test_validate_passes_clean_set() -> None:
    q = _good_q("What does the period $T$ represent?")
    report = validate(QuizSet(items=[q, q, q]))
    assert report.ok, report.failures


def test_validate_flags_missing_question_mark() -> None:
    q = _good_q("This prompt forgets to end with a question.")
    report = validate(QuizSet(items=[q, q, q]))
    assert not report.ok
    assert any("does not end with '?'" in f for f in report.failures)


def test_validate_flags_all_of_the_above() -> None:
    q = _good_q(
        "Pick the option that is 'all of the above'?",
        choices=["x", "y", "z", "all of the above"],
        correct_idx=3,
    )
    report = validate(QuizSet(items=[q, q, q]))
    assert not report.ok
    assert any("all of the above" in f for f in report.failures)


def test_validate_flags_letter_prefix_in_choice() -> None:
    q = _good_q(
        "Which letter prefix is unprofessional?",
        choices=["A. apple", "banana", "cherry", "date"],
    )
    report = validate(QuizSet(items=[q, q, q]))
    assert not report.ok
    assert any("letter prefix" in f for f in report.failures)


def test_validate_flags_trivial_distractor_smell() -> None:
    """Correct choice much longer than median distractor — common LLM tell."""
    q = QuizQuestion(
        prompt="Which of these statements is true?",
        choices=[
            "no",
            "yes",
            "Because the restoring force in simple harmonic motion always "
            "points toward equilibrium and is proportional to displacement.",
            "maybe",
        ],
        correct_idx=2,
        explanation="The third option is the correct rule statement.",
    )
    report = validate(QuizSet(items=[q, q, q]))
    assert not report.ok
    assert any("trivial-distractor" in f for f in report.failures)
