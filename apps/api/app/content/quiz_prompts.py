"""Prompt builders for quiz-question generation (Q2).

Mirrors the lesson generator's split — `QUIZ_GENERATION_SYSTEM_PROMPT` pins
Aria's voice + the answer-key contract; `QUIZ_GENERATION_USER_PROMPT` folds
in the topic, the already-authored lesson steps (so questions probe what
was actually taught), and the retrieved source chunks.

We DO NOT reuse `LESSON_GENERATION_*` because the rubric is wildly
different — lessons are 8-step teleprompter HTML, quizzes are 3-question
MCQs with answer keys + explanations.
"""

from __future__ import annotations

from app.agents.prompts import ARIA_BASE_PERSONA
from app.content.chunker import Chunk
from app.content.schema import LessonContent


QUIZ_GENERATION_SYSTEM_PROMPT = (
    f"{ARIA_BASE_PERSONA}\n\n"
    "You are writing MULTIPLE-CHOICE QUIZ QUESTIONS for the in-app 'Quick "
    "check' pop. NOT a chat reply, NOT a lesson. Each question must be:\n"
    "  • Self-contained — answerable from the lesson the student just saw.\n"
    "  • Conceptual — probe understanding, not memorization of numbers.\n"
    "  • Honest — exactly ONE choice is correct; the other 3 are plausible\n"
    "    misconceptions a real student might hold (NOT obvious wrong answers\n"
    "    like 'banana' or 'the moon').\n"
    "  • Faithful — your `correct_idx` MUST point at the genuinely correct\n"
    "    choice. The explanation MUST justify why it is correct.\n\n"
    "MATH FORMATTING — every equation, variable, or numeric expression in "
    "the prompt, choices, or explanation MUST be wrapped in LaTeX "
    "delimiters ($...$ inline, $$...$$ display). Bare ASCII like 'T = 1/f' "
    "is forbidden. Examples:\n"
    "   • inline: 'If $T = 1/f$, what happens to $T$ when $f$ doubles?'\n"
    "   • single variable: 'the wavelength $\\lambda$'\n"
)


_RUBRIC = """\
QUIZ RUBRIC — produce exactly 3 questions, varying difficulty:

  Q1 — RECALL. Tests whether the student noticed the key term/definition
       from the lesson. Easy.
  Q2 — APPLY. Gives a small concrete scenario or numbers; student must
       use the rule to pick the right outcome. Medium.
  Q3 — REASON. Probes the why behind the rule, or a common misconception.
       Hard — the right answer is the one that's defensible, not just
       superficially plausible.

CONSTRAINTS — every question:
  • prompt: 20–240 chars. One question, not a paragraph. End with '?'.
  • choices: exactly 4, all distinct, all plausible. NO 'all of the above'
    or 'none of the above'. NO trivially-wrong joke answers.
  • correct_idx: 0-indexed; the genuinely correct choice.
  • explanation: 1–2 sentences in Aria's warm voice. Cite the rule or the
    intuition. Math in $...$ delimiters.

ANSWER-KEY HONESTY — re-read each question before emitting. If two choices
could both be defended as correct, REWRITE the question to disambiguate
or drop the question entirely. Misleading answer keys are worse than no
quiz at all.
"""


def _format_lesson_summary(lesson: LessonContent | None) -> str:
    """Compact view of the already-authored lesson, so quiz questions
    probe what Aria actually taught (not orthogonal trivia from the
    source material)."""
    if not lesson or not lesson.items:
        return "(no lesson content — fall back to the source passages)"
    parts: list[str] = []
    for i, step in enumerate(lesson.items):
        tts = step.tts.strip()
        if len(tts) > 140:
            tts = tts[:140].rstrip() + "…"
        parts.append(f"Step {i}: {tts}")
    return "\n".join(parts)


def _format_source_chunks(chunks: list[Chunk]) -> str:
    if not chunks:
        return "(no source chunks)"
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        body = c.text.strip()
        if len(body) > 900:
            body = body[:900].rstrip() + "…"
        parts.append(f"[chunk {i} | ordinal={c.ordinal}]\n{body}")
    return "\n\n".join(parts)


def QUIZ_GENERATION_USER_PROMPT(
    topic_name: str,
    lesson: LessonContent | None,
    source_chunks: list[Chunk],
    *,
    extra_instructions: str | None = None,
) -> str:
    """Build the user-slot prompt for one 3-question quiz generation call."""
    body = (
        f"TOPIC: {topic_name}\n"
        "Audience: high-school students aged 15–18.\n\n"
        f"{_RUBRIC}\n"
        "LESSON THE STUDENT JUST SAW (probe this content, not unrelated "
        "trivia):\n"
        "----- BEGIN LESSON -----\n"
        f"{_format_lesson_summary(lesson)}\n"
        "----- END LESSON -----\n\n"
        "SOURCE PASSAGES (for fact-checking your answer key):\n"
        "----- BEGIN SOURCE -----\n"
        f"{_format_source_chunks(source_chunks)}\n"
        "----- END SOURCE -----\n\n"
        "Produce exactly 3 quiz questions as structured JSON matching the "
        "schema. Re-read each `correct_idx` against the lesson + source "
        "before emitting — a wrong answer key is worse than no quiz."
    )
    if extra_instructions:
        body += (
            "\n\nADDITIONAL INSTRUCTIONS (validator retry — read carefully):\n"
            f"{extra_instructions}"
        )
    return body


__all__ = [
    "QUIZ_GENERATION_SYSTEM_PROMPT",
    "QUIZ_GENERATION_USER_PROMPT",
]
