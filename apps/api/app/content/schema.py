"""Pydantic schemas for the content pipeline (B2).

`LessonContent` is what Gemini Pro emits via structured output and what gets
persisted to ``topics.content``. The shape mirrors the existing hand-authored
seed format (an array of 8 ``{tts, html, dur}`` steps) so the frontend
teleprompter consumes generator output and human-authored output identically.

These schemas are **also** used as `response_schema=` in the Gemini call —
the validator runs as a defence-in-depth gate on top of structured output to
catch model drift the JSON-schema layer can't enforce (term coverage, HTML
allow-listing, monotonic durations, etc.).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LessonStep(BaseModel):
    """One moment of an in-app lesson.

    All three fields are required:

      • ``tts``  — what Aria says (plain prose, ≤120 chars, no HTML, no LaTeX).
      • ``html`` — on-screen teleprompter HTML; allow-listed tag set only.
      • ``dur``  — mm:ss timestamp; monotonically increases across the lesson.
    """

    tts: str = Field(
        ...,
        max_length=120,
        description=(
            "Spoken line for Aria's TTS. Plain prose, two short sentences max, "
            "no HTML and no LaTeX (the TTS layer reads it verbatim)."
        ),
    )
    html: str = Field(
        ...,
        description=(
            "On-screen HTML for the teleprompter. Allowed tags: "
            "span.hl-{y,b,p,g}, em, strong, code. Math must be inside "
            "$...$ or $$...$$ LaTeX delimiters."
        ),
    )
    dur: str = Field(
        ...,
        pattern=r"^\d{2}:\d{2}$",
        description="mm:ss timestamp when this step appears. Monotonically increases.",
    )


class LessonContent(BaseModel):
    """Top-level lesson — exactly 8 steps in author-defined order."""

    items: list[LessonStep] = Field(
        ...,
        min_length=8,
        max_length=8,
        description="Exactly 8 lesson steps. Step 0 is the boilerplate intro.",
    )
