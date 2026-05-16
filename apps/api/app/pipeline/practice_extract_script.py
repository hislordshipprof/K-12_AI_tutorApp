"""Worksheet-extraction verification script — practice-quiz source (task 2.8).

Task 2.8 *Verify*: extract a unit's tagged worksheet questions into structured
MCQs and review them. This script is the runnable proof that the extraction
core works on a real unit — it loads the unit's latest segmentation's
`practice_tags`, downloads the worksheet PDFs, runs `extract_unit_practice`,
and prints how many questions were extracted vs. flagged and why.

Run:
    python -m app.pipeline.practice_extract_script <unit_id>
    python -m app.pipeline.practice_extract_script        # default: the e2e
                                                          # demo Fluids unit

With no `unit_id` the script resolves the fixed `e2e-fluids-demo` course/unit
the `e2e_script.py` proof hangs off (the same default-to-the-demo-unit
convenience the e2e script provides) — so a run right after the e2e proof
needs no copy-pasted uuid.

This makes ONE live PRO-model Gemini call PER worksheet material — the
orchestrator runs it to verify the acceptance criteria; the unit tests use a
mocked Gemini.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from app.pipeline.practice_extract import ExtractError, extract_unit_practice

# The fixed demo course slug the e2e proof (`e2e_script.py`) hangs off — used
# to resolve a default `unit_id` when none is given on the command line.
_DEMO_COURSE_SLUG = "e2e-fluids-demo"


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so unicode in question text renders on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _resolve_demo_unit(supabase: Any) -> str | None:
    """Resolve the `e2e-fluids-demo` course's first unit id, or None.

    Mirrors `e2e_script._ensure_demo_course_unit`'s lookup keys — the course
    by its fixed `slug`, then the unit by `(course_id, n=1)` — but READ-only
    (this script never creates the demo course/unit; it only reuses one a
    prior e2e run already built).
    """
    course_resp = (
        supabase.table("courses")
        .select("id")
        .eq("slug", _DEMO_COURSE_SLUG)
        .limit(1)
        .execute()
    )
    course_rows = list(getattr(course_resp, "data", None) or [])
    if not course_rows:
        return None
    course_id = str(course_rows[0]["id"])
    unit_resp = (
        supabase.table("units")
        .select("id")
        .eq("course_id", course_id)
        .eq("n", 1)
        .limit(1)
        .execute()
    )
    unit_rows = list(getattr(unit_resp, "data", None) or [])
    return str(unit_rows[0]["id"]) if unit_rows else None


async def run(unit_id: str | None) -> int:
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        print(
            "[practice-extract] Supabase is not configured — set SUPABASE_URL "
            "+ SUPABASE_SERVICE_ROLE_KEY",
            file=sys.stderr,
        )
        return 3

    if unit_id is None:
        unit_id = _resolve_demo_unit(supabase)
        if unit_id is None:
            print(
                "[practice-extract] no unit_id given and the "
                f"{_DEMO_COURSE_SLUG!r} demo unit does not exist — run "
                "`python -m app.pipeline.e2e_script` first, or pass a unit_id.",
                file=sys.stderr,
            )
            return 2
        print(
            f"[practice-extract] using the {_DEMO_COURSE_SLUG!r} demo unit "
            f"{unit_id}",
            file=sys.stderr,
        )

    print(
        f"[practice-extract] extracting tagged worksheet questions for unit "
        f"{unit_id} (ONE live PRO-model call per worksheet material)...",
        file=sys.stderr,
    )
    try:
        result = await extract_unit_practice(unit_id)
    except ExtractError as e:
        print(
            f"[practice-extract] EXTRACTION FAILED ({e.reason}): {e}",
            file=sys.stderr,
        )
        return 6

    # ── Report ───────────────────────────────────────────────────────────────
    total = len(result.questions) + len(result.flagged)
    print("\n" + "=" * 72)
    print(f"PRACTICE EXTRACTION REPORT — unit {unit_id}")
    print("=" * 72)
    print(
        f"\n  {total} tagged worksheet question(s): "
        f"{len(result.questions)} extracted, {len(result.flagged)} flagged.\n"
    )

    if result.questions:
        print(f"  EXTRACTED — {len(result.questions)} usable MCQ(s):\n")
        for pq in result.questions:
            q = pq.question
            print(
                f"  • [m{pq.material_idx}:p{pq.page_idx} {pq.question_label}] "
                f"{q.prompt}"
            )
            for j, c in enumerate(q.choices):
                mark = "*" if j == q.correct_idx else " "
                print(f"      [{mark}] {c}")
            print(f"      why: {q.explanation}\n")

    if result.flagged:
        print(
            f"  FLAGGED — {len(result.flagged)} question(s) NOT turned into "
            "an MCQ (acceptance criterion 3 — flagged, not invented):\n"
        )
        for fq in result.flagged:
            print(
                f"  • [m{fq.material_idx}:p{fq.page_idx} {fq.question_label}] "
                f"{fq.reason}"
            )
        print()

    print("=" * 72)
    print(
        "[practice-extract] OK — the extracted PracticeQuestion(s) carry the "
        "(material_idx, page_idx, question_label) triple generate_quiz's "
        "practice path matches tags on; flagged questions were surfaced, not "
        "guessed."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.practice_extract_script",
        description=(
            "Extract a unit's tagged worksheet questions into structured "
            "practice-quiz MCQs (task 2.8)."
        ),
    )
    parser.add_argument(
        "unit_id",
        nargs="?",
        default=None,
        help=(
            "the unit to extract worksheet questions for (default: the "
            "e2e-fluids-demo unit a prior e2e run created)"
        ),
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.unit_id))


if __name__ == "__main__":
    raise SystemExit(main())
