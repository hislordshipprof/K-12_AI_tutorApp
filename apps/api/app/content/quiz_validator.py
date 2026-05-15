"""Defence-in-depth gates for `QuizSet` output (Q2).

Pydantic catches most schema-level issues (4 choices, correct_idx range,
length bounds). This validator catches *content* failure modes the schema
can't see:

  • Banned patterns ("all of the above", "none of the above", "obviously")
  • Trivial-distractor sniffer (correct choice is much longer than the
    others — a known LLM tell)
  • Prompt must end with '?'
  • Choices must not contain the answer letter ("A.", "B)") as prefix
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.content.quiz_schema import QuizQuestion, QuizSet

VALIDATOR_VERSION = "quiz-v1"

_BANNED_PHRASES = (
    "all of the above",
    "none of the above",
    "both a and b",
    "both b and c",
    "obviously",
)

# "A. ", "A) ", "(A) " etc. at the very start of a choice — looks unprofessional
# and confuses the index↔letter mapping in the UI.
_CHOICE_LETTER_PREFIX = re.compile(r"^\s*[\(\[]?[A-Da-d][\)\].:\-]\s+")


@dataclass
class QuizValidationReport:
    ok: bool
    failures: list[str] = field(default_factory=list)


def _validate_question(idx: int, q: QuizQuestion) -> list[str]:
    fails: list[str] = []
    prompt = q.prompt.strip()
    if not prompt.endswith("?"):
        fails.append(f"Q{idx + 1}: prompt does not end with '?'")

    low = prompt.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in low:
            fails.append(f"Q{idx + 1}: banned phrase {phrase!r} in prompt")

    for j, choice in enumerate(q.choices):
        clow = choice.lower()
        for phrase in _BANNED_PHRASES:
            if phrase in clow:
                fails.append(
                    f"Q{idx + 1}.{j}: banned phrase {phrase!r} in choice"
                )
        if _CHOICE_LETTER_PREFIX.match(choice):
            fails.append(
                f"Q{idx + 1}.{j}: choice starts with a letter prefix "
                f"(remove 'A.'/'B)' style)"
            )

    # Trivial-distractor sniff: correct choice >2.5x longer than median of
    # the other 3 is a LLM tell. Not fatal, but flag it.
    others = [len(q.choices[i]) for i in range(4) if i != q.correct_idx]
    others.sort()
    median_other = others[len(others) // 2] if others else 0
    correct_len = len(q.choices[q.correct_idx])
    if median_other > 0 and correct_len > 2.5 * median_other:
        fails.append(
            f"Q{idx + 1}: correct choice ({correct_len} chars) is much "
            f"longer than median distractor ({median_other} chars) — "
            f"trivial-distractor smell"
        )

    return fails


def validate(quiz: QuizSet) -> QuizValidationReport:
    """Run all content gates over a `QuizSet`."""
    failures: list[str] = []
    for i, q in enumerate(quiz.items):
        failures.extend(_validate_question(i, q))
    return QuizValidationReport(ok=not failures, failures=failures)


__all__ = ["QuizValidationReport", "VALIDATOR_VERSION", "validate"]
