"""Quiz-generation verification script — auto-quiz one topic (task 2.6).

Task 2.6 *Verify*: generate (and re-generate) a topic's quiz. This script is
the runnable proof that the AUTO quiz-generation core works on a real topic's
comprehension slice — no HTTP endpoint, no DB needed (it supplies the topic's
title + comprehension slice directly), matching `generate_script.py`'s style.

Run (uses the same built-in Fluids "Buoyancy" topic as `generate_script.py`):
    python -m app.pipeline.quiz_script

This makes ONE live Gemini call on the PRO model — the orchestrator runs it to
verify the acceptance criteria; the unit tests use a mocked Gemini.
"""

from __future__ import annotations

import asyncio
import sys

from app.pipeline.generate import ComprehensionSlice, SliceFigure, SliceSection
from app.pipeline.quiz import QuizError, generate_quiz_set


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so unicode in quiz text renders on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


# The same lesson-sized Fluids "Buoyancy" topic `generate_script.py` uses, so
# the quiz the orchestrator sees lines up with the lesson it generated.
_FLUIDS_TOPIC_TITLE = "Buoyancy and Archimedes' Principle"
_FLUIDS_SLICE = ComprehensionSlice(
    sections=[
        SliceSection(
            title="The buoyant force",
            key_points=[
                "A submerged object feels greater pressure on its bottom "
                "than its top.",
                "That pressure difference produces a net upward force — the "
                "buoyant force.",
            ],
        ),
        SliceSection(
            title="Archimedes' principle",
            key_points=[
                "The buoyant force equals the weight of the fluid the object "
                "displaces.",
                "An object floats when the buoyant force balances its weight.",
            ],
        ),
    ],
    figures=[
        SliceFigure(
            description="A block submerged in water with pressure arrows "
            "longer on the bottom face than the top."
        ),
    ],
)


async def run() -> int:
    print(
        f"[quiz] auto-generating a quiz for {_FLUIDS_TOPIC_TITLE!r} "
        "(ONE live PRO-model call)...",
        file=sys.stderr,
    )
    try:
        quiz = await generate_quiz_set(
            topic_title=_FLUIDS_TOPIC_TITLE,
            comprehension_slice=_FLUIDS_SLICE,
        )
    except QuizError as e:
        print(f"[quiz] QUIZ GENERATION FAILED ({e.reason}): {e}", file=sys.stderr)
        return 6

    print(f"\n[quiz] generated a {len(quiz.items)}-question quiz:\n")
    for i, q in enumerate(quiz.items):
        print(f"  Q{i + 1}. {q.prompt}")
        for j, c in enumerate(q.choices):
            mark = "*" if j == q.correct_idx else " "
            print(f"     [{mark}] {c}")
        print(f"     why: {q.explanation}\n")
    print(
        "[quiz] OK — quiz generated from the topic's comprehension slice; "
        "the DB function tags each row with topics.active_version_id so it "
        "versions with the lesson."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
