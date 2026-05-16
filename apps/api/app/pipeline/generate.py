"""Per-topic lesson generation + scene assignment (teacher-authoring, task 2.5).

`teacher-authoring.md` §6 "Generate (per confirmed topic)": for each topic the
teacher confirmed, the model writes the Aria lesson from THAT topic's slice of
the unit `comprehension` JSON + the topic's `design_notes`. This module is the
sibling of the existing OpenStax `app.content.generator` — same destination
(`topics.content`), different source.

What 2.5 changes vs the OpenStax generator:
  * **Persona is parameterised** — built per course via task 2.4's
    `build_persona(subject, grade_band, teaching_style)`, not the hard-coded
    physics tutor.
  * **Depth scales with the material** — the fixed 8-step rubric is dropped;
    the lesson is as long as the topic's content needs.
  * **Each step gains an optional `page`** — the `id` of a `topic_pages` row,
    i.e. which claimed slide the step is taught over. A step with no slide
    omits `page` and falls back to the chalkboard (§7).
  * **Each step gets a `scene`** — reusing the EXISTING scene system: the
    typed `scene_tagger` registry first, a Claude-authored `custom-svg`
    fallback for steps no typed scene fits, and a guaranteed text-board scene
    so every step ends with a non-empty scene.

Step shape (§6) — today's `{tts, html, dur}` plus `scene` (always set) and an
optional `page`:

    { tts, html, dur, scene, page? }

Scope (Phase 2 is backend-only, proven by a script — `CLAUDE.md`): plain
service functions, NO HTTP endpoints, the `pipeline_jobs` 'generate' job is
NOT wired (consistent with how 2.1/2.2/2.3 were scoped). 2.5 CONSUMES a
confirmed topic — it does not build the confirm-breakdown step. The CORE is
decoupled from the DB so it is data-testable and live-verifiable standalone
(`generate_script.py`).

Public API:
    * ``generate_lesson``  — pure-ish core: a topic's data in -> a list of
      scene-assigned `Step`s out. Mocked-Gemini testable.
    * ``generate_topic``   — DB function: load a topic + its course + its
      `topic_pages` + the unit's latest `comprehension`, run the core, write a
      `topic_versions` row and mirror it into `topics.content` (the §4
      invariant).
    * ``GenerateError``    — malformed model output / missing inputs.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.agents.prompts import SOCRATIC_RULES, build_persona
from app.content import scene_tagger
from app.core.config import settings
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class GenerateError(RuntimeError):
    """Lesson generation could not run or produced an unusable result.

    Carries a stable `reason` code so callers branch without string matching:
      * ``malformed_output`` — the model returned output that does not
                               validate against the step schema; rejected,
                               never written.
      * ``no_topic``         — the DB function was given a topic id that has
                               no `topics` row.
      * ``no_segmentation``  — the topic's unit has no `unit_segmentations`
                               row, so there is no `comprehension` to slice.
      * ``no_supabase``      — the DB function needs a Supabase client.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Inputs — the topic's comprehension slice + its claimed pages.
# ─────────────────────────────────────────────────────────────────────────────
# `comprehension_slice` is the subset of the §2.2 unit `comprehension` that
# covers ONE topic — its sections, figures and per-page classification. These
# models intentionally mirror the relevant fields of
# `app.pipeline.segment.{SectionRead,FigureDesc,PageClass}` so the DB function
# can build a slice straight from a stored `unit_segmentations.comprehension`.


class SliceSection(BaseModel):
    """One section of the topic's comprehension slice — a teachable beat."""

    title: str = Field(..., description="the section heading / short label")
    key_points: list[str] = Field(
        default_factory=list, description="the teachable points of this section"
    )


class SliceFigure(BaseModel):
    """One figure the topic covers, with a plain-language description."""

    description: str = Field(..., description="what the figure shows")


class ComprehensionSlice(BaseModel):
    """A topic's portion of the unit `comprehension` — the generation source.

    Built from §2.2's `Comprehension`: the `sections` / `figures` that the
    topic's pages cover, plus the figure descriptions for its claimed slides.
    The lesson is written ONLY from this slice + `design_notes` — never from
    the whole unit — so a topic's lesson stays on its own material.
    """

    sections: list[SliceSection] = Field(default_factory=list)
    figures: list[SliceFigure] = Field(default_factory=list)


class TopicPage(BaseModel):
    """One claimed page of a topic — a `topic_pages` row the lesson may show.

    `id` is the stable `topic_pages` row id a generated step's `page` field
    points at (§4). `material_idx` / `page_idx` / `role` are the page's
    coordinates, surfaced to the model so it can choose WHICH slide a step is
    taught over. `ord` is the page's display order within the topic.
    """

    id: str = Field(..., description="the topic_pages row id — a step's `page` ref")
    material_idx: int = Field(default=0, ge=0)
    page_idx: int = Field(default=0, ge=0)
    role: str = Field(default="slide", description="'slide' | 'figure'")
    ord: int = Field(default=0, description="display order within the topic")


# ─────────────────────────────────────────────────────────────────────────────
# Model output shape — the lesson the model emits (the step schema is ALSO the
# Gemini `response_schema`, so structured output lands typed; validation then
# rejects malformed output before any row is written).
# ─────────────────────────────────────────────────────────────────────────────
class GeneratedStep(BaseModel):
    """One step as the MODEL emits it — `{tts, html, dur}` + a 1-based page ref.

    `page_ref` is 1-based into the topic's claimed-page list passed in the
    prompt (1 = the first page), or 0/null when the step is NOT taught over a
    slide (a chalkboard step). The generator maps a valid `page_ref` to the
    real `topic_pages` row `id`; the model never sees raw ids. `scene` is NOT
    in this schema — the generator assigns it after parsing, reusing the
    existing scene system.
    """

    tts: str = Field(
        ...,
        max_length=240,
        description=(
            "Spoken line for Aria's TTS. Plain prose, two short sentences max, "
            "no HTML and no LaTeX (the TTS layer reads it verbatim)."
        ),
    )
    # NOTE: the prompt asks for <=120 chars (the spoken-line target); the
    # schema cap is a looser 240 only so an occasional model overshoot does
    # not hard-fail parsing and abort a whole multi-topic run. 120 stays the
    # quality target, 240 is the crash guard.
    html: str = Field(
        ...,
        description=(
            "On-screen teleprompter HTML. Allowed tags: span.hl-{y,b,p,g}, "
            "em, strong, code. Math inside $...$ or $$...$$ LaTeX delimiters."
        ),
    )
    dur: str = Field(
        ...,
        pattern=r"^\d{2}:\d{2}$",
        description="mm:ss timestamp when this step appears. Monotonically increases.",
    )
    page_ref: int = Field(
        default=0,
        ge=0,
        description=(
            "1-based index into the topic's claimed-page list — which slide "
            "this step is taught over. 0 (or omitted) = a chalkboard step "
            "with no slide."
        ),
    )


class GeneratedLesson(BaseModel):
    """The whole lesson the model emits — as many steps as the material needs.

    DEPTH SCALES (§6): there is NO fixed step count. `min_length=2` only
    guards against a degenerate empty/one-step lesson; there is deliberately
    NO `max_length` — the rubric's old 8-step cap is dropped.
    """

    items: list[GeneratedStep] = Field(
        ...,
        min_length=2,
        description=(
            "The lesson steps, in play order. As long as the topic's content "
            "needs — not a fixed count."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Output shape — a finished, scene-assigned step (what lands in topics.content).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Step:
    """A finished lesson step — the `{tts, html, dur, scene, page?}` §6 shape.

    `scene` is ALWAYS set (a typed scene, a Claude-authored `custom-svg`
    scene, or the text-board fallback) — never null. `page` is the `id` of a
    `topic_pages` row when the step is taught over a slide, else `None` (the
    classroom then falls back to the chalkboard, §7).
    """

    tts: str
    html: str
    dur: str
    scene: dict[str, Any]
    page: str | None = None

    def to_content(self) -> dict[str, Any]:
        """Serialise to the `topics.content` JSON step shape.

        `page` is included ONLY when set — a chalkboard step omits the key
        entirely (§6: "Steps with no `page` fall back to the chalkboard").
        """
        out: dict[str, Any] = {
            "tts": self.tts,
            "html": self.html,
            "dur": self.dur,
            "scene": self.scene,
        }
        if self.page is not None:
            out["page"] = self.page
        return out


# The guaranteed-non-null fallback scene. When neither the typed registry nor
# the Claude fallback fits a step, it still gets a scene — the plain animated
# text chalkboard the classroom already renders. This is what makes "EVERY
# step has a scene" true unconditionally.
_CHALKBOARD_SCENE: dict[str, Any] = {"type": "chalkboard", "params": {}}


# ─────────────────────────────────────────────────────────────────────────────
# Retry policy — same transient-error heuristic as services.gemini / generator.
# ─────────────────────────────────────────────────────────────────────────────
_RETRYABLE = (
    "rate limit", "429", "500", "502", "503", "504",
    "overloaded", "deadline exceeded", "unavailable", "internal error",
)


def _is_retryable(exc: BaseException) -> bool:
    return any(p in str(exc).lower() for p in _RETRYABLE)


def _retry_policy() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prompt — depth-scaled, persona-parameterised lesson generation.
# ─────────────────────────────────────────────────────────────────────────────
# The system slot is the per-course persona (task 2.4's `build_persona`) plus
# the teleprompter-content framing and the math-formatting rule. It is BUILT
# per call — not a module constant — because the persona varies per course.
def _build_system_prompt(
    subject: str | None,
    grade_band: str | None,
    teaching_style: str | None,
) -> str:
    """Assemble the generation system prompt for one course.

    `build_persona` (task 2.4) returns the per-course Aria — the built-in
    physics persona when all three are None (a Recommended course), an
    assembled subject/grade/style persona otherwise. The teleprompter framing
    + the math-formatting rule (lifted from `SOCRATIC_RULES` rule 8, the one
    rule that also governs lesson HTML) are appended.
    """
    persona = build_persona(subject, grade_band, teaching_style)
    # Rule 8 of SOCRATIC_RULES is the LaTeX math-formatting rule — the single
    # Socratic rule that also applies to teleprompter HTML. Surface it so the
    # model does not emit bare-ASCII equations.
    math_rule = SOCRATIC_RULES.split("8. MATH FORMATTING")[-1]
    return (
        f"{persona}\n\n"
        "You are writing lesson content for the in-app teleprompter, NOT a "
        "chat reply. Each step is what Aria says + what the student sees, for "
        "ONE moment of the lesson. Stay in Aria's voice the whole way.\n\n"
        "MATH FORMATTING — " + math_rule.strip()
    )


def _format_slice(slice_: ComprehensionSlice) -> str:
    """Render the topic's comprehension slice as a model-readable block."""
    lines: list[str] = []
    if slice_.sections:
        lines.append("SECTIONS (the teachable beats of this topic):")
        for i, s in enumerate(slice_.sections, 1):
            lines.append(f"  [{i}] {s.title}")
            for kp in s.key_points:
                lines.append(f"      - {kp}")
    else:
        lines.append("SECTIONS: (none extracted — teach from the summary)")
    if slice_.figures:
        lines.append("\nFIGURES the topic covers:")
        for f in slice_.figures:
            lines.append(f"  - {f.description}")
    return "\n".join(lines)


def _format_pages(pages: list[TopicPage]) -> str:
    """Render the topic's claimed pages as a 1-based, model-readable list."""
    if not pages:
        return (
            "CLAIMED PAGES: (none — this topic has no slides; every step is a "
            "chalkboard step, so leave `page_ref` 0 on every step)."
        )
    lines = [
        "CLAIMED PAGES — the slides this topic is taught over. Reference one "
        "from a step via its 1-based number in `page_ref` (or 0 for a "
        "chalkboard step with no slide):",
    ]
    for i, p in enumerate(pages, 1):
        lines.append(f"  [{i}] a {p.role} page (material {p.material_idx}, "
                     f"page {p.page_idx})")
    return "\n".join(lines)


def _build_user_prompt(
    *,
    topic_title: str,
    topic_summary: str,
    comprehension_slice: ComprehensionSlice,
    design_notes: str | None,
    topic_pages: list[TopicPage],
) -> str:
    """Build the user-slot prompt for one topic's depth-scaled generation."""
    notes_block = (
        f"\nTEACHER'S DESIGN NOTES (per-lesson guidance — honour these):\n"
        f"{design_notes.strip()}\n"
        if design_notes and design_notes.strip()
        else ""
    )
    return (
        f"TOPIC: {topic_title}\n"
        f"SUMMARY: {topic_summary}\n"
        f"{notes_block}\n"
        f"{_format_slice(comprehension_slice)}\n\n"
        f"{_format_pages(topic_pages)}\n\n"
        "WRITE THE LESSON as a list of steps. Rules:\n"
        "  - DEPTH SCALES WITH THE MATERIAL. There is NO fixed number of "
        "steps — a short topic is a short lesson, a rich topic is a longer "
        "one. Do NOT pad to a target count and do NOT cram. One idea per "
        "step.\n"
        "  - Step 0 MUST be the boilerplate intro, EXACTLY: "
        'tts "Preparing your lesson." / html "Preparing your lesson…" / '
        'dur "00:00" / page_ref 0.\n'
        "  - Every other step: `tts` <= 120 chars, max 2 sentences, plain "
        "prose, no HTML, no LaTeX. `html` is the teleprompter line — allowed "
        "tags span.hl-{y,b,p,g}, em, strong, code; all math inside $...$ or "
        "$$...$$. `dur` is mm:ss and strictly increases down the lesson.\n"
        "  - For a step taught over one of the claimed slides, set `page_ref` "
        "to that slide's 1-based number. For a step with no slide, leave "
        "`page_ref` 0 — it plays on the chalkboard.\n"
        "  - Anchor everything in the sections / figures / design notes "
        "above. Do NOT introduce content the topic's material does not "
        "support.\n"
        "Return the lesson as structured JSON matching the schema."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scene assignment — reuse the EXISTING scene system (task: §6 "also assigns
# each step a scene", typed registry first, Claude-authored fallback).
# ─────────────────────────────────────────────────────────────────────────────
async def _assign_scene(
    step: GeneratedStep,
    *,
    topic_title: str,
    scene_drawer: Any | None,
) -> dict[str, Any]:
    """Assign ONE step a scene, reusing the existing scene mechanism.

    The exact mechanism the OpenStax pipeline uses, in order:
      1. **Typed registry** — `app.content.scene_tagger.tag()` keyword-matches
         the step text against the 12 typed chalkboard scenes (the same call
         `scripts.tag_scenes` and the live Q&A endpoint use). First hit wins.
      2. **Claude-authored fallback** — for a step no typed scene fits,
         `scene_drawer` (the `_draw_step_anthropic`-style drawer from
         `scripts.generate_scene_svgs`) draws a structured `custom-svg` scene.
         Injected by the caller; `None` skips this rung (mocked-Gemini tests).
      3. **Text-board fallback** — if neither fits, the step still gets a
         scene: the plain animated chalkboard. So EVERY step ends with a
         non-empty `scene` — never null.
    """
    title = scene_tagger.headline_from_html(step.html)
    text = f"{step.tts} {step.html}"

    # 1. Typed scene registry.
    typed = scene_tagger.tag(text, title)
    if typed is not None:
        return typed

    # 2. Claude-authored custom-svg fallback (when a drawer is wired).
    if scene_drawer is not None:
        try:
            params = await scene_drawer(topic_title, text)
        except Exception as exc:  # noqa: BLE001 — a drawing failure must not
            # sink the whole lesson; the step just falls back to the board.
            log.warning("generate_scene_drawer_failed", error=str(exc))
            params = None
        if params:
            return {"type": "custom-svg", "params": params}

    # 3. Guaranteed text-board scene — every step has a scene.
    return dict(_CHALKBOARD_SCENE)


# ─────────────────────────────────────────────────────────────────────────────
# Core — generate a topic's lesson, decoupled from the DB.
# ─────────────────────────────────────────────────────────────────────────────
async def generate_lesson(
    *,
    topic_title: str,
    topic_summary: str,
    comprehension_slice: ComprehensionSlice,
    design_notes: str | None,
    subject: str | None,
    grade_band: str | None,
    teaching_style: str | None,
    topic_pages: list[TopicPage],
    gemini: GeminiService | None = None,
    scene_drawer: Any | None = None,
) -> list[Step]:
    """Generate one topic's depth-scaled Aria lesson, scene-assigned.

    The pure-ish core (no DB): build the persona-parameterised prompt from the
    topic's comprehension slice + `design_notes`, call the PRO model, parse +
    VALIDATE the steps, map each step's `page_ref` to a real `topic_pages` row
    `id`, and assign every step a `scene`.

    Args:
        topic_title / topic_summary: the confirmed topic's title + summary.
        comprehension_slice: the topic's portion of the §2.2 unit
            `comprehension` — its sections + figures.
        design_notes: the topic's per-lesson teacher guidance (may be None).
        subject / grade_band / teaching_style: the course's persona
            parameters (task 2.4 `build_persona`). All None on a Recommended
            course — Aria stays the built-in physics tutor.
        topic_pages: the topic's claimed `topic_pages` rows (each with its
            stable `id`). A step's `page` is set to one of these ids.
        gemini: a `GeminiService`; constructed lazily if omitted.
        scene_drawer: an async `(topic_title, step_text) -> params | None`
            drawer for the Claude-authored `custom-svg` fallback. `None`
            (the default, and what mocked tests pass) skips that rung — a
            step that no typed scene fits then gets the text-board scene.

    Model: per-topic generation runs on the PRO slot
    (`settings.gemini_model_pro`, `model-strategy.md` §6).

    Raises `GenerateError('malformed_output')` if the model output does not
    parse / validate — a bad lesson is never returned, never written.
    """
    svc = gemini or GeminiService()

    system = _build_system_prompt(subject, grade_band, teaching_style)
    user = _build_user_prompt(
        topic_title=topic_title,
        topic_summary=topic_summary,
        comprehension_slice=comprehension_slice,
        design_notes=design_notes,
        topic_pages=topic_pages,
    )

    log.info(
        "generate_lesson_start",
        topic=topic_title,
        model=settings.gemini_model_pro,
        pages=len(topic_pages),
        sections=len(comprehension_slice.sections),
    )

    config: dict[str, Any] = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "response_schema": GeneratedLesson,
        "temperature": 0.6,
    }
    client = svc.client

    async for attempt in _retry_policy():
        with attempt:
            response = await client.aio.models.generate_content(
                model=settings.gemini_model_pro,
                contents=user,
                config=config,
            )
            lesson = _parse_lesson(response)
            break  # success — leave the retry loop
    else:  # pragma: no cover — tenacity reraises on exhaustion
        raise GenerateError("malformed_output", "generation retry loop exhausted")

    # Map each step's 1-based `page_ref` to a real `topic_pages` row id, then
    # assign every step a scene. `page_ref` out of range -> no page (the model
    # over-claimed) -> the step falls back to the chalkboard.
    steps: list[Step] = []
    for gs in lesson.items:
        page_id: str | None = None
        if 1 <= gs.page_ref <= len(topic_pages):
            page_id = topic_pages[gs.page_ref - 1].id
        scene = await _assign_scene(
            gs, topic_title=topic_title, scene_drawer=scene_drawer
        )
        steps.append(
            Step(tts=gs.tts, html=gs.html, dur=gs.dur, scene=scene, page=page_id)
        )

    log.info(
        "generate_lesson_ok",
        topic=topic_title,
        steps=len(steps),
        slide_backed=sum(1 for s in steps if s.page is not None),
    )
    return steps


def _parse_lesson(response: Any) -> GeneratedLesson:
    """Turn a Gemini response into a validated `GeneratedLesson`.

    Rejects malformed model output — anything that does not parse / validate
    against the step schema raises `GenerateError('malformed_output')` so a
    bad lesson is never returned. Accepts the SDK's parsed `.parsed` object
    (structured output) or a JSON-coercion fallback over `.text`.
    """
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeneratedLesson):
        return parsed
    if isinstance(parsed, dict):
        try:
            return GeneratedLesson.model_validate(parsed)
        except ValidationError as e:
            raise GenerateError(
                "malformed_output",
                f"generation output failed schema validation: {e}",
            ) from e

    raw = getattr(response, "text", "") or ""
    if not raw:
        raise GenerateError(
            "malformed_output",
            "generation model returned no parseable output (no .parsed, no .text)",
        )
    try:
        return GeneratedLesson.model_validate_json(raw)
    except ValidationError as e:
        raise GenerateError(
            "malformed_output",
            f"generation output failed schema validation: {e}",
        ) from e


# ─────────────────────────────────────────────────────────────────────────────
# Comprehension-slice builder — slice the unit `comprehension` for one topic.
# ─────────────────────────────────────────────────────────────────────────────
def topic_comprehension_slice(
    *,
    topic_title: str,
    key_points: list[str],
    comprehension: dict[str, Any],
    claimed: list[tuple[int, int]],
) -> ComprehensionSlice:
    """Build ONE topic's comprehension slice from the topic's OWN key points.

    The §2.2 fix (Bug B): a `ProposedTopic` now carries its own `key_points`
    — the specific teachable points THAT topic must cover. A topic's slice is
    therefore those points, NOT the unit-wide `Comprehension.sections` (which
    hold all ~16 of the unit's key points and were wrongly handed to every
    topic — so a "Density" lesson was graded against buoyancy/pressure points
    that are not its job).

    The slice keeps the SAME `{sections, figures}` shape so downstream
    consumers (`_format_slice`, `validate._flatten_key_points`,
    `quiz._slice_to_chunks`) need no change — but `sections` is now a SINGLE
    synthetic `SliceSection` titled with the topic name, carrying the topic's
    own `key_points`. `figures` are the unit `Comprehension.figures` on one of
    the topic's `claimed` `(material_idx, page_idx)` pages.

    Args:
        topic_title: the topic's name — the synthetic section's title.
        key_points: the topic's `ProposedTopic.key_points` — its own
            teachable points (the source of truth for generation + validation).
        comprehension: the `unit_segmentations.comprehension` payload — read
            ONLY for its `figures` (the per-figure descriptions).
        claimed: the `(material_idx, page_idx)` set of the topic's pages —
            filters `comprehension.figures` to the topic's own slides.
    """
    claimed_set = set(claimed)
    points = [str(k) for k in key_points if str(k).strip()]
    sections = (
        [SliceSection(title=topic_title, key_points=points)] if points else []
    )
    figures = [
        SliceFigure(description=str(f.get("description", "")))
        for f in (comprehension.get("figures") or [])
        if isinstance(f, dict)
        and (int(f.get("material_idx", -1)), int(f.get("page_idx", -1)))
        in claimed_set
    ]
    return ComprehensionSlice(sections=sections, figures=figures)


def slice_comprehension(
    comprehension: dict[str, Any],
    claimed: list[tuple[int, int]],
) -> ComprehensionSlice:
    """Slice a unit's stored `comprehension` JSON down to ONE topic.

    `comprehension` is a `unit_segmentations.comprehension` payload (the §2.2
    `Comprehension` shape). `claimed` is the `(material_idx, page_idx)` set of
    the topic's pages. The slice keeps:
      * every `figure` on a claimed page (figure descriptions feed the lesson);
      * `sections` — the unit `Comprehension.sections` carry no page index, so
        all of them are kept.

    NOTE (Bug B): this unit-wide-sections slicer is NO LONGER on the lesson
    generation / validation path — those now use `topic_comprehension_slice`
    over the topic's OWN `ProposedTopic.key_points`. It is retained for
    `quiz.py`'s auto path (task 2.6), whose call site is unchanged.
    """
    claimed_set = set(claimed)
    sections = [
        SliceSection(
            title=str(s.get("title", "")),
            key_points=[str(k) for k in (s.get("key_points") or [])],
        )
        for s in (comprehension.get("sections") or [])
        if isinstance(s, dict)
    ]
    figures = [
        SliceFigure(description=str(f.get("description", "")))
        for f in (comprehension.get("figures") or [])
        if isinstance(f, dict)
        and (int(f.get("material_idx", -1)), int(f.get("page_idx", -1)))
        in claimed_set
    ]
    return ComprehensionSlice(sections=sections, figures=figures)


# ─────────────────────────────────────────────────────────────────────────────
# DB function — load a confirmed topic, generate, write a version, mirror it.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GenerateResult:
    """Outcome of `generate_topic` — the new `topic_versions` row id, its
    label, and the generated lesson's step count."""

    topic_id: str
    version_id: str
    label: str
    step_count: int
    slide_backed: int = 0
    pages: list[str] = field(default_factory=list)  # the step `page` ids set


async def generate_topic(
    topic_id: str,
    *,
    gemini: GeminiService | None = None,
    scene_drawer: Any | None = None,
) -> GenerateResult:
    """Generate a confirmed topic's lesson and persist it as a new version.

    The flow (`teacher-authoring.md` §4, §6):

      1. Load the `topics` row (title, summary, `design_notes`). Missing ->
         `GenerateError('no_topic')`.
      2. Walk topic -> unit -> course for the persona parameters
         (`subject` / `grade_band` / `teaching_style`).
      3. Load the topic's `topic_pages` rows (the claimed slides).
      4. Load the unit's LATEST `unit_segmentations` and slice its
         `comprehension` for this topic. No segmentation ->
         `GenerateError('no_segmentation')`.
      5. Run `generate_lesson` — the persona-parameterised, depth-scaled,
         scene-assigned core.
      6. INSERT a `topic_versions` row (`content` = the steps, a "v1"/"v2…"
         label, `created_at`, `created_by`).
      7. Set `topics.active_version_id` to the new row AND mirror the SAME
         `content` into `topics.content` — the §4 invariant
         `topics.content == topic_versions[active_version_id].content`.

    Args:
        topic_id: the confirmed topic to generate.
        gemini / scene_drawer: passed through to `generate_lesson`.

    Returns a `GenerateResult`. Requires a configured Supabase service-role
    client.
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise GenerateError(
            "no_supabase",
            "generate_topic requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. Load the topic. `n` is the unit-scoped 1-based ordinal — proposed
    #    topic[n-1] in the latest segmentation is THIS topic (confirm_breakdown
    #    maps proposed-topic[i] -> the `topics` row with `n = i + 1`).
    topic_resp = (
        supabase.table("topics")
        .select("id,name,summary,design_notes,unit_id,n")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    topic = getattr(topic_resp, "data", None)
    if not topic:
        raise GenerateError("no_topic", f"no topics row for id {topic_id}")
    unit_id = topic.get("unit_id")

    # 2. topic -> unit -> course for the persona parameters.
    subject = grade_band = teaching_style = None
    if unit_id:
        unit_resp = (
            supabase.table("units")
            .select("id,course_id")
            .eq("id", unit_id)
            .single()
            .execute()
        )
        unit = getattr(unit_resp, "data", None) or {}
        course_id = unit.get("course_id")
        if course_id:
            course_resp = (
                supabase.table("courses")
                .select("id,subject,grade_band,teaching_style")
                .eq("id", course_id)
                .single()
                .execute()
            )
            course = getattr(course_resp, "data", None) or {}
            subject = course.get("subject")
            grade_band = course.get("grade_band")
            teaching_style = course.get("teaching_style")

    # 3. The topic's claimed pages (`topic_pages` rows, in display order).
    pages_resp = (
        supabase.table("topic_pages")
        .select("id,material_id,page_idx,role,ord")
        .eq("topic_id", topic_id)
        .order("ord")
        .execute()
    )
    page_rows: list[dict[str, Any]] = list(getattr(pages_resp, "data", None) or [])
    # The model addresses pages by a `material_idx`; map each distinct
    # `material_id` to a stable 0-based index so the slice + the prompt agree.
    material_ids: list[str] = []
    for r in page_rows:
        mid = str(r.get("material_id"))
        if mid not in material_ids:
            material_ids.append(mid)
    topic_pages = [
        TopicPage(
            id=str(r["id"]),
            material_idx=material_ids.index(str(r.get("material_id")))
            if r.get("material_id") is not None
            else 0,
            page_idx=int(r.get("page_idx") or 0),
            role=str(r.get("role") or "slide"),
            ord=int(r.get("ord") or 0),
        )
        for r in page_rows
    ]

    # 4. The unit's latest segmentation, sliced for this topic from the
    #    topic's OWN `ProposedTopic.key_points` (Bug B).
    seg_resp = (
        supabase.table("unit_segmentations")
        .select("id,comprehension,proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    seg_rows = list(getattr(seg_resp, "data", None) or [])
    if not seg_rows:
        raise GenerateError(
            "no_segmentation",
            f"unit {unit_id} has no unit_segmentations — cannot slice a "
            "comprehension for this topic",
        )
    comprehension = seg_rows[0].get("comprehension") or {}
    # Locate THIS topic's `ProposedTopic` — confirm_breakdown maps
    # proposed-topic[i] -> the `topics` row with `n = i + 1`, so the
    # topic's own key points live at `proposed.topics[n - 1]`.
    proposed = seg_rows[0].get("proposed") or {}
    proposed_topics = list(proposed.get("topics") or [])
    topic_n = int(topic.get("n") or 0)
    key_points: list[str] = []
    if 1 <= topic_n <= len(proposed_topics):
        pt = proposed_topics[topic_n - 1]
        if isinstance(pt, dict):
            key_points = [str(k) for k in (pt.get("key_points") or [])]
    claimed = [(p.material_idx, p.page_idx) for p in topic_pages]
    comprehension_slice = topic_comprehension_slice(
        topic_title=str(topic.get("name") or ""),
        key_points=key_points,
        comprehension=comprehension,
        claimed=claimed,
    )

    # 5. Run the core.
    steps = await generate_lesson(
        topic_title=str(topic.get("name") or ""),
        topic_summary=str(topic.get("summary") or ""),
        comprehension_slice=comprehension_slice,
        design_notes=topic.get("design_notes"),
        subject=subject,
        grade_band=grade_band,
        teaching_style=teaching_style,
        topic_pages=topic_pages,
        gemini=gemini,
        scene_drawer=scene_drawer,
    )
    content = [s.to_content() for s in steps]

    # 6. INSERT a topic_versions row. The label is "v{n}" where n counts the
    #    topic's existing versions + 1 — re-generating a topic appends a row.
    existing = (
        supabase.table("topic_versions")
        .select("id")
        .eq("topic_id", topic_id)
        .execute()
    )
    version_n = len(list(getattr(existing, "data", None) or [])) + 1
    version_id = str(uuid.uuid4())
    label = f"v{version_n}"
    now = _dt.datetime.now(_dt.UTC).isoformat()
    supabase.table("topic_versions").insert(
        {
            "id": version_id,
            "topic_id": topic_id,
            "content": content,
            "label": label,
            "created_at": now,
        }
    ).execute()

    # 7. Make the new version active AND mirror its content into topics.content
    #    — the §4 invariant: topics.content == the active version's content.
    supabase.table("topics").update(
        {"active_version_id": version_id, "content": content}
    ).eq("id", topic_id).execute()

    log.info(
        "generate_topic_ok",
        topic_id=topic_id,
        version_id=version_id,
        label=label,
        steps=len(steps),
    )
    return GenerateResult(
        topic_id=topic_id,
        version_id=version_id,
        label=label,
        step_count=len(steps),
        slide_backed=sum(1 for s in steps if s.page is not None),
        pages=[s.page for s in steps if s.page is not None],
    )


__all__ = [
    "GenerateError",
    "SliceSection",
    "SliceFigure",
    "ComprehensionSlice",
    "TopicPage",
    "GeneratedStep",
    "GeneratedLesson",
    "Step",
    "generate_lesson",
    "slice_comprehension",
    "topic_comprehension_slice",
    "generate_topic",
    "GenerateResult",
]
