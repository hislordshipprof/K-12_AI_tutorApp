"""Lesson-generation verification script — generate one topic (task 2.5).

Task 2.5 *Verify*: generate a Fluids topic and inspect its steps. This script
is the runnable proof that the generation CORE works on a real topic — no HTTP
endpoint, no DB confirm step needed (it supplies the topic's
title/summary/comprehension-slice/topic_pages directly), matching
`segment_script.py`'s style.

Run (uses a small built-in Fluids "Buoyancy & Archimedes' principle" topic):
    python -m app.pipeline.generate_script

This makes ONE live Gemini call on the PRO model — the orchestrator runs it on
the real Fluids topic to verify the acceptance criteria; the unit tests use a
mocked Gemini. Pass `--no-draw` to skip the Claude-authored scene fallback
(then any step no typed scene fits gets the text-board scene).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.pipeline.generate import (
    ComprehensionSlice,
    GenerateError,
    SliceFigure,
    SliceSection,
    TopicPage,
    generate_lesson,
)


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so unicode in lesson text renders on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


# A real, lesson-sized Fluids topic — one of the 10 the 2.2 live run proposed
# on the actual `Unit 8 - Fluids - AP Physics 1.pptx` deck (the "Buoyancy"
# group). The slice + pages are supplied directly so 2.5 is verifiable
# standalone, without the (later) confirm-breakdown step.
_FLUIDS_TOPIC_TITLE = "Buoyancy and Archimedes' Principle"
_FLUIDS_TOPIC_SUMMARY = (
    "Why objects float or sink in a fluid. Introduces the buoyant force as "
    "the net upward push from pressure differences, and Archimedes' "
    "principle relating it to the weight of displaced fluid."
)
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


async def run(draw: bool) -> int:
    # The two claimed slides of this topic. In a real run these come from the
    # topic's `topic_pages` rows; here they are supplied directly so the core
    # can be verified standalone. The ids are what a step's `page` is set to.
    topic_pages = [
        TopicPage(id="page-buoyant-force", material_idx=0, page_idx=22,
                  role="slide", ord=0),
        TopicPage(id="page-archimedes", material_idx=0, page_idx=24,
                  role="slide", ord=1),
    ]

    scene_drawer = None
    if draw:
        # Reuse the existing Claude-authored scene fallback from the scene
        # system — the same `_draw_step_anthropic` the OpenStax pipeline uses.
        import os

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            from anthropic import AsyncAnthropic

            from scripts.generate_scene_svgs import _draw_step_anthropic

            client = AsyncAnthropic(api_key=anthropic_key)

            async def scene_drawer(topic: str, step_text: str):  # type: ignore[misc]
                return await _draw_step_anthropic(
                    client, "claude-sonnet-4-6", topic, step_text
                )
        else:
            print(
                "[generate] ANTHROPIC_API_KEY not set — Claude scene fallback "
                "disabled; steps no typed scene fits get the text board.",
                file=sys.stderr,
            )

    print(
        f"[generate] generating lesson for {_FLUIDS_TOPIC_TITLE!r} "
        "(ONE live PRO-model call)...",
        file=sys.stderr,
    )
    try:
        steps = await generate_lesson(
            topic_title=_FLUIDS_TOPIC_TITLE,
            topic_summary=_FLUIDS_TOPIC_SUMMARY,
            comprehension_slice=_FLUIDS_SLICE,
            design_notes=None,
            subject="Physics",
            grade_band="9-12",
            teaching_style=None,
            topic_pages=topic_pages,
            scene_drawer=scene_drawer,
        )
    except GenerateError as e:
        print(f"[generate] GENERATION FAILED ({e.reason}): {e}", file=sys.stderr)
        return 6

    page_by_id = {p.id: i + 1 for i, p in enumerate(topic_pages)}
    slide_backed = sum(1 for s in steps if s.page is not None)
    print(
        f"\n[generate] generated a {len(steps)}-step lesson "
        f"({slide_backed} slide-backed, {len(steps) - slide_backed} "
        "chalkboard):\n"
    )
    for i, s in enumerate(steps):
        scene_type = s.scene.get("type", "?")
        page = (
            f"slide #{page_by_id[s.page]} ({s.page})"
            if s.page is not None
            else "chalkboard"
        )
        print(f"  step {i} [{s.dur}]  scene={scene_type}  page={page}")
        print(f"     tts:  {s.tts}")
        print(f"     html: {s.html}")
    # A blunt sanity line for the orchestrator: every step has a scene, no cap.
    assert all(s.scene for s in steps), "a step has no scene"
    print(
        f"\n[generate] OK — every step has a scene; depth not capped "
        f"(8-step rubric dropped); {slide_backed} step(s) reference a "
        "real topic_pages id."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.generate_script",
        description="Generate one confirmed topic's Aria lesson (task 2.5).",
    )
    parser.add_argument(
        "--no-draw",
        action="store_true",
        help="skip the Claude-authored custom-svg scene fallback",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(draw=not args.no_draw))


if __name__ == "__main__":
    raise SystemExit(main())
