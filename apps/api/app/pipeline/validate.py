"""Lesson validator — does a generated lesson cover the teacher's key points?
(teacher-authoring pipeline, task 2.7)

`teacher-authoring.md` §6 "Validate": "Check the lesson actually covers the
teacher's key points (the existing validator pattern, run against the
`comprehension` output instead of OpenStax). On failure the generation job
retries once; a second failure leaves the topic in `draft` with the
validator's gap report surfaced in the board. **Publish is blocked until a
topic's lesson validates.**"

This module is the teacher-pipeline sibling of `app.content.validator` (the
OpenStax B2 validator). What it reuses, and what it changes:

  * REUSED — the *pattern*: a structured `ValidationReport` dataclass
    (`ok`/`passed` + a flat list of human-readable problems) returned by a
    single `validate()` entry point, the same shape the OpenStax pipeline
    feeds back into the generator on retry (`app.content.cli` ->
    `_format_retry_instructions`).
  * CHANGED — the *source of truth*: the OpenStax validator gate-1 checks a
    lesson against `required_terms` / `required_equations` mechanically
    extracted from the OpenStax book. A teacher lesson has no OpenStax book —
    its "key points" are the §2.2 `comprehension` slice (the sections the
    model read out of the teacher's own upload). So this validator runs
    against the `comprehension` slice instead.
  * CHANGED — the *method*: OpenStax key points are short canonical
    terms/equations, so a substring scan works. A `comprehension` key point
    is a full prose sentence ("A submerged object feels greater pressure on
    its bottom than its top") — a substring scan cannot tell whether a lesson
    *teaches* that idea. So coverage is a **model-graded** check, on the same
    model tier the OpenStax validator's generator uses (the PRO slot —
    `model-strategy.md` §6, the reasoning-heavy content tier). The model is
    asked, per key point, whether the lesson teaches it.

The result is a `ValidationReport`: `passed: bool` + a `gap_report` listing
the uncovered / weakly-covered key points. The retry-once-then-draft flow in
`app.pipeline.generate_and_validate` consumes it.

Scope (Phase 2 is backend-only, proven by a script — `CLAUDE.md`): plain
service functions, NO HTTP endpoints. The CORE (`validate_lesson`) is
decoupled from the DB and Gemini-mockable.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.pipeline.generate import (
    ComprehensionSlice,
    GenerateResult,
    Step,
    generate_topic,
    topic_comprehension_slice,
)
from app.services.gemini import GeminiService

log = get_logger(__name__)

VALIDATOR_VERSION = "teacher-lesson-v1"


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class ValidateError(RuntimeError):
    """Validation could not run (as distinct from a lesson that FAILED — a
    failed lesson is a `ValidationReport(passed=False)`, not an exception).

    Carries a stable `reason` code:
      * ``malformed_output`` — the model's grading response did not parse /
                               validate against the grading schema.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# The gap report — which of the teacher's key points the lesson misses.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class KeyPointGap:
    """One key point the lesson does NOT adequately teach.

    `section` is the comprehension section the key point came from; `key_point`
    is the point itself; `verdict` is the model's grade — ``'missing'`` (not
    taught at all) or ``'weak'`` (mentioned but not actually taught);
    `detail` is the model's one-line explanation, surfaced to the teacher.
    """

    section: str
    key_point: str
    verdict: str  # 'missing' | 'weak'
    detail: str


@dataclass
class ValidationReport:
    """Result of validating one generated lesson against its comprehension
    slice — the teacher-pipeline analogue of `app.content.validator`'s report.

    `passed` is True only when EVERY key point is covered. `gaps` is the gap
    report — the uncovered / weak key points; empty when `passed`. `covered`
    / `total` count the key points the lesson does / could cover.
    `failures` is a flat list of human-readable problem strings (the same
    shape the OpenStax validator returns) so the retry path can feed them
    straight back into the generator.
    """

    passed: bool
    gaps: list[KeyPointGap] = field(default_factory=list)
    covered: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Alias of `passed` — matches `app.content.validator.ValidationReport.ok`."""
        return self.passed

    def gap_report_text(self) -> str:
        """Render the gap report as the text surfaced in the board / persisted
        on the failed generate job's `error` field (§6)."""
        if self.passed:
            return "Lesson validated: every key point is covered."
        lines = [
            f"Lesson failed validation — {len(self.gaps)} of {self.total} key "
            f"point(s) not adequately taught:",
        ]
        for g in self.gaps:
            lines.append(
                f"  • [{g.verdict}] ({g.section}) {g.key_point}\n    {g.detail}"
            )
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Model output shape — the per-key-point grade the model emits.
# ─────────────────────────────────────────────────────────────────────────────
class _PointGrade(BaseModel):
    """The model's grade for ONE key point of the comprehension slice."""

    section: str = Field(..., description="the section the key point belongs to")
    key_point: str = Field(..., description="the key point being graded, verbatim")
    verdict: str = Field(
        ...,
        description=(
            "'covered' — the lesson actually teaches this idea; 'weak' — it is "
            "mentioned but not really taught; 'missing' — the lesson does not "
            "address it at all."
        ),
    )
    detail: str = Field(
        ...,
        description="one short sentence justifying the verdict, for the teacher",
    )


class _LessonGrade(BaseModel):
    """The model's full grade — one `_PointGrade` per key point of the slice."""

    grades: list[_PointGrade] = Field(
        default_factory=list,
        description="one grade per key point, in the order the key points were given",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Retry policy — the same transient-error heuristic the rest of the pipeline
# uses (services.gemini / generate.py).
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
# Prompt — model-graded coverage check.
# ─────────────────────────────────────────────────────────────────────────────
_VALIDATE_SYSTEM_PROMPT = (
    "You are the validation stage of a teacher-authoring pipeline for a K-12 "
    "tutoring app. A teacher uploaded their own material; an AI then wrote a "
    "lesson from it. Your job is to check, point by point, whether the "
    "generated lesson ACTUALLY TEACHES the key points the teacher's material "
    "covers — not merely name-drops them.\n\n"
    "Be strict but fair. A key point is 'covered' only if a student who "
    "played the lesson would genuinely learn that idea. If the lesson just "
    "mentions the term in passing without explaining it, that is 'weak'. If "
    "the lesson does not address the idea at all, that is 'missing'. Grade "
    "EVERY key point you are given, in order. Do not invent key points."
)


def _flatten_key_points(slice_: ComprehensionSlice) -> list[tuple[str, str]]:
    """Flatten the comprehension slice into `(section_title, key_point)` pairs.

    The teacher's "key points" are the §2.2 `comprehension` slice's per-section
    `key_points` — the teachable points the model read out of the upload.
    A section with no key points contributes its title as a single point so
    a thin section is still checked.
    """
    pairs: list[tuple[str, str]] = []
    for s in slice_.sections:
        if s.key_points:
            for kp in s.key_points:
                pairs.append((s.title, kp))
        else:
            pairs.append((s.title, s.title))
    return pairs


def _render_lesson(steps: list[Step]) -> str:
    """Render the generated lesson's steps as a model-readable transcript."""
    lines: list[str] = []
    for i, s in enumerate(steps):
        lines.append(f"  [step {i}] {s.tts}")
    return "\n".join(lines)


def _build_validate_prompt(
    *,
    topic_title: str,
    key_points: list[tuple[str, str]],
    steps: list[Step],
) -> str:
    """Build the user-slot prompt — the lesson transcript + the key points."""
    kp_lines = [
        f"  [{i + 1}] (section: {section}) {kp}"
        for i, (section, kp) in enumerate(key_points)
    ]
    return (
        f"TOPIC: {topic_title}\n\n"
        "THE GENERATED LESSON (Aria's spoken narration, step by step):\n"
        f"{_render_lesson(steps)}\n\n"
        "THE TEACHER'S KEY POINTS — every one must be taught by the lesson "
        "above:\n"
        + "\n".join(kp_lines)
        + "\n\nFor EACH key point, return a grade: 'covered', 'weak', or "
        "'missing', with one short sentence of justification. Return "
        "structured JSON matching the schema, one grade per key point, in "
        "order."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core — validate a generated lesson against its comprehension slice.
# ─────────────────────────────────────────────────────────────────────────────
async def validate_lesson(
    *,
    topic_title: str,
    steps: list[Step],
    comprehension_slice: ComprehensionSlice,
    gemini: GeminiService | None = None,
) -> ValidationReport:
    """Validate that a generated lesson covers the teacher's key points.

    The pure-ish core (no DB): flatten the §2.2 `comprehension` slice into
    key points, ask the model — per key point — whether the lesson teaches
    it, and assemble a `ValidationReport` + gap report.

    A lesson `passes` only when EVERY key point grades 'covered'. A 'weak' or
    'missing' grade lands the point in the gap report and fails the lesson.

    Args:
        topic_title: the topic whose lesson is being validated.
        steps: the generated lesson's `Step`s (from `generate_lesson`).
        comprehension_slice: the topic's §2.2 comprehension slice — its
            sections + key points are the teacher's content of record.
        gemini: a `GeminiService`; constructed lazily if omitted.

    Model: validation is a model-graded check — it runs on the PRO slot
    (`settings.gemini_model_pro`), the same content-quality tier the OpenStax
    validator's generator uses (`model-strategy.md` §6).

    A slice with NO key points (nothing teachable) trivially `passes` — there
    is nothing to fail against. Raises `ValidateError('malformed_output')` if
    the model's grading response cannot be parsed.
    """
    key_points = _flatten_key_points(comprehension_slice)

    # No key points to check — a slice with nothing teachable cannot fail.
    if not key_points:
        log.info("validate_lesson_no_key_points", topic=topic_title)
        return ValidationReport(passed=True, gaps=[], covered=0, total=0)

    svc = gemini or GeminiService()
    system = _VALIDATE_SYSTEM_PROMPT
    user = _build_validate_prompt(
        topic_title=topic_title, key_points=key_points, steps=steps
    )

    log.info(
        "validate_lesson_start",
        topic=topic_title,
        key_points=len(key_points),
        steps=len(steps),
        model=settings.gemini_model_pro,
    )

    config: dict[str, Any] = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "response_schema": _LessonGrade,
        "temperature": 0.2,
    }
    client = svc.client

    async for attempt in _retry_policy():
        with attempt:
            response = await client.aio.models.generate_content(
                model=settings.gemini_model_pro,
                contents=user,
                config=config,
            )
            grade = _parse_grade(response)
            break  # success — leave the retry loop
    else:  # pragma: no cover — tenacity reraises on exhaustion
        raise ValidateError("malformed_output", "validation retry loop exhausted")

    return _build_report(key_points, grade)


def _parse_grade(response: Any) -> _LessonGrade:
    """Turn a Gemini response into a validated `_LessonGrade`.

    Mirrors `generate._parse_lesson`: accepts the SDK's parsed `.parsed`
    object (structured output) or a JSON-coercion fallback over `.text`.
    Malformed output raises `ValidateError('malformed_output')`.
    """
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, _LessonGrade):
        return parsed
    if isinstance(parsed, dict):
        try:
            return _LessonGrade.model_validate(parsed)
        except ValidationError as e:
            raise ValidateError(
                "malformed_output",
                f"validation grade failed schema validation: {e}",
            ) from e

    raw = getattr(response, "text", "") or ""
    if not raw:
        raise ValidateError(
            "malformed_output",
            "validation model returned no parseable output (no .parsed, no .text)",
        )
    try:
        return _LessonGrade.model_validate_json(raw)
    except ValidationError as e:
        raise ValidateError(
            "malformed_output",
            f"validation grade failed schema validation: {e}",
        ) from e


def _build_report(
    key_points: list[tuple[str, str]],
    grade: _LessonGrade,
) -> ValidationReport:
    """Assemble a `ValidationReport` from the model's per-point grades.

    A key point is `covered` only if a grade explicitly says so. A key point
    the model omitted from its response is treated as `missing` — a lesson
    cannot pass on an un-graded point.
    """
    # Index the model's grades by (section, key_point) for a robust match,
    # falling back to the key-point text alone (the model may lightly reword
    # the section label).
    by_pair: dict[tuple[str, str], _PointGrade] = {}
    by_kp: dict[str, _PointGrade] = {}
    for g in grade.grades:
        by_pair[(g.section.strip(), g.key_point.strip())] = g
        by_kp.setdefault(g.key_point.strip(), g)

    gaps: list[KeyPointGap] = []
    covered = 0
    for section, kp in key_points:
        g = by_pair.get((section.strip(), kp.strip())) or by_kp.get(kp.strip())
        verdict = (g.verdict.strip().lower() if g else "missing")
        detail = (
            g.detail.strip()
            if g and g.detail.strip()
            else "the validator returned no grade for this key point"
        )
        if verdict == "covered":
            covered += 1
        else:
            # Anything that is not an explicit 'covered' is a gap. Normalise
            # an unexpected verdict string to 'weak' so the report stays in
            # the {missing, weak} vocabulary.
            norm = verdict if verdict in ("missing", "weak") else "weak"
            gaps.append(
                KeyPointGap(
                    section=section, key_point=kp, verdict=norm, detail=detail
                )
            )

    passed = not gaps
    failures = (
        []
        if passed
        else [
            f"[{g.verdict}] key point not taught — ({g.section}) {g.key_point}"
            for g in gaps
        ]
    )
    report = ValidationReport(
        passed=passed,
        gaps=gaps,
        covered=covered,
        total=len(key_points),
        failures=failures,
    )
    log.info(
        "validate_lesson_done",
        passed=passed,
        covered=covered,
        total=len(key_points),
        gaps=len(gaps),
    )
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Retry-once-then-draft flow — generate a topic, validate, retry ONCE, leave
# the topic `draft` either way (validated vs gap-reported).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GenerateValidateResult:
    """Outcome of `generate_and_validate` — the topic's final state.

    `passed` is whether the lesson validated. `attempts` is how many times the
    lesson was generated (1 = passed first try, 2 = a retry happened). `report`
    is the validator's `ValidationReport` for the FINAL attempt — its gap
    report is what the teacher sees when `passed` is False. `generate` is the
    `GenerateResult` of the final (persisted) generation. The topic ends
    `status='draft'` in BOTH cases — see the function docstring.
    """

    topic_id: str
    passed: bool
    attempts: int
    report: ValidationReport
    generate: GenerateResult


def _topic_comprehension_slice(supabase: Any, topic_id: str) -> ComprehensionSlice:
    """Build a topic's comprehension slice from the unit's latest segmentation.

    Mirrors `generate_topic`'s slice step (Bug B): topic -> unit -> latest
    `unit_segmentations` -> `topic_comprehension_slice` over the topic's OWN
    `ProposedTopic.key_points`. The validator therefore grades the lesson
    against the TOPIC's handful of key points — the same ones the generator
    wrote it from — not the unit's ~16 unit-wide points.
    """
    topic_resp = (
        supabase.table("topics")
        .select("id,name,unit_id,n")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    topic = getattr(topic_resp, "data", None) or {}
    unit_id = topic.get("unit_id")

    pages_resp = (
        supabase.table("topic_pages")
        .select("material_id,page_idx")
        .eq("topic_id", topic_id)
        .order("ord")
        .execute()
    )
    page_rows = list(getattr(pages_resp, "data", None) or [])
    material_ids: list[str] = []
    for r in page_rows:
        mid = str(r.get("material_id"))
        if mid not in material_ids:
            material_ids.append(mid)
    claimed = [
        (
            material_ids.index(str(r.get("material_id")))
            if r.get("material_id") is not None
            else 0,
            int(r.get("page_idx") or 0),
        )
        for r in page_rows
    ]

    seg_resp = (
        supabase.table("unit_segmentations")
        .select("id,comprehension,proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    seg_rows = list(getattr(seg_resp, "data", None) or [])
    comprehension = (seg_rows[0].get("comprehension") if seg_rows else {}) or {}
    # The topic's OWN key points — confirm_breakdown maps proposed-topic[i]
    # -> the `topics` row with `n = i + 1`, so they live at
    # `proposed.topics[n - 1]`.
    proposed = (seg_rows[0].get("proposed") if seg_rows else {}) or {}
    proposed_topics = list(proposed.get("topics") or [])
    topic_n = int(topic.get("n") or 0)
    key_points: list[str] = []
    if 1 <= topic_n <= len(proposed_topics):
        pt = proposed_topics[topic_n - 1]
        if isinstance(pt, dict):
            key_points = [str(k) for k in (pt.get("key_points") or [])]
    return topic_comprehension_slice(
        topic_title=str(topic.get("name") or ""),
        key_points=key_points,
        comprehension=comprehension,
        claimed=claimed,
    )


def _steps_from_content(content: Any) -> list[Step]:
    """Rebuild `Step` objects from a persisted `topics.content` JSON list.

    `generate_topic` mirrors the generated steps into `topics.content` as
    `{tts, html, dur, scene, page?}` dicts; the validator only needs the
    `tts` / `html` / `dur` text, so the rebuilt `Step`s carry the page/scene
    through unchanged.
    """
    steps: list[Step] = []
    for d in content or []:
        if not isinstance(d, dict):
            continue
        steps.append(
            Step(
                tts=str(d.get("tts", "")),
                html=str(d.get("html", "")),
                dur=str(d.get("dur", "")),
                scene=d.get("scene") or {},
                page=d.get("page"),
            )
        )
    return steps


def _surface_gap_report(supabase: Any, topic_id: str, report: ValidationReport) -> None:
    """Persist the gap report on the topic's most recent `generate` job.

    §6: a second validation failure "leaves the topic in `draft` with the
    validator's gap report surfaced in the board". The board polls
    `pipeline_jobs`, so the natural home is the `error` field of the topic's
    latest `generate` job. If the topic has no `generate` job row (the e2e
    script calls the stage functions directly — Phase 2 does not wire the job
    runner), there is nothing to write to; the report is still returned on the
    `GenerateValidateResult`, which is the caller's surface.
    """
    try:
        job_resp = (
            supabase.table("pipeline_jobs")
            .select("id,created_at")
            .eq("topic_id", topic_id)
            .eq("kind", "generate")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        job_rows = list(getattr(job_resp, "data", None) or [])
        if not job_rows:
            return
        now = _dt.datetime.now(_dt.UTC).isoformat()
        supabase.table("pipeline_jobs").update(
            {"error": report.gap_report_text(), "updated_at": now}
        ).eq("id", job_rows[0]["id"]).execute()
    except Exception as e:  # noqa: BLE001 — surfacing the report must not crash
        log.warning("validate_gap_report_surface_failed", error=str(e))


async def generate_and_validate(
    topic_id: str,
    *,
    gemini: GeminiService | None = None,
    scene_drawer: Any | None = None,
    validation_slice: ComprehensionSlice | None = None,
) -> GenerateValidateResult:
    """Generate a topic's lesson, validate it, retry ONCE on failure (§6).

    The retry-once-then-draft flow:

      1. Run `generate_topic` (task 2.5) — writes a `topic_versions` row and
         mirrors `topics.content`.
      2. Validate the generated lesson against the topic's §2.2 comprehension
         slice (`validate_lesson`).
      3. If validation FAILS, retry `generate_topic` ONCE — a fresh version,
         then re-validate.
      4. The topic ends `status='draft'` EITHER WAY:
         * validated — `draft` is the correct end state; per §6 "publish is
           blocked until a topic's lesson validates" means validation is a
           *precondition* for publish, NOT auto-publish. Publishing is a
           later, explicit teacher action (Phase 3).
         * still failing after the retry — `draft` with the validator's gap
           report surfaced (on the topic's latest `generate` job's `error`,
           and on the returned `GenerateValidateResult.report`).

    So the topic's `status` is `'draft'` in both outcomes — the difference is
    `passed` (validated) vs. a non-empty `report.gaps` (gap-reported). This
    function never sets `status='published'`.

    Args:
        topic_id: the confirmed topic to generate + validate.
        gemini: a `GeminiService`; constructed lazily if omitted.
        scene_drawer: the Claude-authored scene fallback passed through to
            `generate_topic` (see `generate.generate_lesson`).
        validation_slice: an OPTIONAL override for the slice the lesson is
            GRADED against. Normally the validator grades a topic against
            its own `_topic_comprehension_slice`. When this is given, the
            generated lesson is graded against THIS slice instead (both the
            first attempt and the retry). The task 2.7 e2e's deliberate
            "starved topic" run passes the WHOLE unit's key points here —
            far more than one topic's pages cover — so the lesson reliably
            fails validation and the topic lands `draft` + gap-reported.

    Returns a `GenerateValidateResult`. Requires a configured Supabase
    service-role client (the slice + the gap-report surfacing read/write the
    DB; `generate_topic` itself also needs it).
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()

    # The comprehension slice is the validator's source of truth — resolve it
    # once; both the first attempt and the retry validate against it. A caller
    # may OVERRIDE it (the e2e's deliberate-failure run); otherwise it is the
    # topic's own slice loaded from the DB.
    comprehension_slice = validation_slice or (
        _topic_comprehension_slice(supabase, topic_id)
        if supabase is not None
        else ComprehensionSlice()
    )

    attempts = 0
    gen: GenerateResult | None = None
    report: ValidationReport | None = None

    # Up to TWO attempts — the first generation, then ONE retry on failure.
    for attempt in range(2):
        attempts = attempt + 1
        log.info("generate_and_validate_attempt", topic_id=topic_id, attempt=attempts)
        gen = await generate_topic(
            topic_id,
            gemini=gemini,
            scene_drawer=scene_drawer,
        )
        steps = _steps_from_content(
            _load_topic_content(supabase, topic_id) if supabase is not None else []
        )
        report = await validate_lesson(
            topic_title=_load_topic_title(supabase, topic_id)
            if supabase is not None
            else "",
            steps=steps,
            comprehension_slice=comprehension_slice,
            gemini=gemini,
        )
        if report.passed:
            break  # validated — no retry needed

    assert gen is not None and report is not None  # the loop runs ≥ once

    # The topic ends `draft` either way — generate_topic never set a status,
    # and a confirmed teacher topic starts `draft` (confirm_breakdown). We do
    # NOT publish here. On a still-failing lesson, surface the gap report.
    if not report.passed and supabase is not None:
        _surface_gap_report(supabase, topic_id, report)

    log.info(
        "generate_and_validate_done",
        topic_id=topic_id,
        passed=report.passed,
        attempts=attempts,
        gaps=len(report.gaps),
    )
    return GenerateValidateResult(
        topic_id=topic_id,
        passed=report.passed,
        attempts=attempts,
        report=report,
        generate=gen,
    )


def _load_topic_content(supabase: Any, topic_id: str) -> Any:
    """Load the topic's freshly-mirrored `topics.content` (the active version)."""
    resp = (
        supabase.table("topics")
        .select("content")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    return (getattr(resp, "data", None) or {}).get("content")


def _load_topic_title(supabase: Any, topic_id: str) -> str:
    """Load the topic's `name` for the validation prompt."""
    resp = (
        supabase.table("topics")
        .select("name")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    return str((getattr(resp, "data", None) or {}).get("name") or "")


__all__ = [
    "ValidateError",
    "KeyPointGap",
    "ValidationReport",
    "VALIDATOR_VERSION",
    "validate_lesson",
    "GenerateValidateResult",
    "generate_and_validate",
]
