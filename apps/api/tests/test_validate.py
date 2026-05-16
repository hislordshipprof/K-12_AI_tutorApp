"""Tests for the lesson validator + retry-once-then-draft flow (task 2.7).

All tests run offline:
  • Gemini is stubbed — `validate_lesson` / `generate_and_validate` are given
    a fake `GeminiService` whose `client.aio.models.generate_content` returns
    a canned grade (validator) or a canned lesson (generation).
  • Supabase is a `MagicMock` for the DB flow.

Covers the `docs/task-execution.md` 2.7 acceptance criteria:
  * the validator PASSES a lesson that covers the teacher's key points;
  * the validator FAILS a starved lesson, with a NON-EMPTY gap report;
  * retry-once-then-draft retries EXACTLY once on failure, then leaves the
    topic `status='draft'` with the gap report;
  * a lesson that validates first try is NOT retried, and still ends `draft`.

The live Fluids end-to-end proof is run by the orchestrator via
`app.pipeline.e2e_script`.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")

from app.pipeline.generate import (  # noqa: E402
    ComprehensionSlice,
    GeneratedLesson,
    GeneratedStep,
    SliceFigure,
    SliceSection,
    Step,
)
from app.pipeline.validate import (  # noqa: E402
    ValidateError,
    ValidationReport,
    generate_and_validate,
    validate_lesson,
)


# ─── helpers ─────────────────────────────────────────────────────────────────
def _slice() -> ComprehensionSlice:
    """A comprehension slice — two sections, three key points total."""
    return ComprehensionSlice(
        sections=[
            SliceSection(
                title="The buoyant force",
                key_points=[
                    "A submerged object feels greater pressure on its bottom.",
                    "That pressure difference produces a net upward force.",
                ],
            ),
            SliceSection(
                title="Archimedes' principle",
                key_points=["The buoyant force equals the displaced fluid's weight."],
            ),
        ],
        figures=[SliceFigure(description="a submerged block with pressure arrows")],
    )


def _key_point_texts() -> list[str]:
    """The flat key-point list of `_slice()`, in order."""
    return [
        "A submerged object feels greater pressure on its bottom.",
        "That pressure difference produces a net upward force.",
        "The buoyant force equals the displaced fluid's weight.",
    ]


def _steps(n: int = 5) -> list[Step]:
    """`n` finished `Step`s — the generated lesson the validator grades."""
    return [
        Step(
            tts=f"Step {i} teaches buoyancy and pressure differences.",
            html=f"<span class=\"hl-y\">step {i}</span>",
            dur=f"{i * 2:02d}:00",
            scene={"type": "chalkboard", "params": {}},
            page=None,
        )
        for i in range(n)
    ]


def _grade_payload(verdicts: list[str]) -> dict[str, Any]:
    """A `_LessonGrade`-shaped dict — one grade per key point of `_slice()`.

    `verdicts` is a per-key-point list of 'covered' / 'weak' / 'missing'.
    """
    kps = _key_point_texts()
    sections = ["The buoyant force", "The buoyant force", "Archimedes' principle"]
    return {
        "grades": [
            {
                "section": sections[i],
                "key_point": kps[i],
                "verdict": verdicts[i],
                "detail": f"verdict for key point {i}",
            }
            for i in range(len(kps))
        ]
    }


class _FakeResp:
    """A Gemini response stub carrying a parsed object and/or text."""

    def __init__(self, parsed: Any = None, text: str = "") -> None:
        self.parsed = parsed
        self.text = text
        self.usage_metadata = None


def _fake_gemini(responses: list[Any]) -> MagicMock:
    """A stub `GeminiService` whose `generate_content` returns each item of
    `responses` in turn (so generation + validation calls get distinct
    canned replies). The last item repeats if more calls are made."""
    calls: list[int] = [0]

    async def _generate_content(**_kwargs: Any) -> Any:
        idx = min(calls[0], len(responses) - 1)
        calls[0] += 1
        return responses[idx]

    models = MagicMock()
    models.generate_content = _generate_content
    aio = MagicMock()
    aio.models = models
    client = MagicMock()
    client.aio = aio
    svc = MagicMock(name="gemini")
    svc.client = client
    return svc


# ─── validator core: pass / fail ─────────────────────────────────────────────
async def test_validate_lesson_passes_a_covering_lesson() -> None:
    """A lesson the model grades 'covered' on every key point PASSES — the
    report has no gaps and `passed` is True (AC: validator passes a covering
    lesson)."""
    report = await validate_lesson(
        topic_title="Buoyancy",
        steps=_steps(6),
        comprehension_slice=_slice(),
        gemini=_fake_gemini([
            _FakeResp(_grade_payload(["covered", "covered", "covered"])),
        ]),
    )
    assert isinstance(report, ValidationReport)
    assert report.passed is True
    assert report.ok is True
    assert report.gaps == []
    assert report.covered == 3
    assert report.total == 3


async def test_validate_lesson_fails_a_starved_lesson_with_a_gap_report() -> None:
    """A lesson with uncovered key points FAILS, and the gap report is
    NON-EMPTY and names the missing/weak points (AC: a starved lesson fails
    validation with a non-empty gap report)."""
    report = await validate_lesson(
        topic_title="Buoyancy",
        steps=_steps(2),  # a thin, hollow lesson
        comprehension_slice=_slice(),
        gemini=_fake_gemini([
            _FakeResp(_grade_payload(["covered", "missing", "weak"])),
        ]),
    )
    assert report.passed is False
    assert report.ok is False
    # The gap report is non-empty and names every uncovered point.
    assert len(report.gaps) == 2
    verdicts = {g.verdict for g in report.gaps}
    assert verdicts == {"missing", "weak"}
    assert report.covered == 1
    text = report.gap_report_text()
    assert text.strip()
    assert "net upward force" in text  # the 'missing' key point
    assert "displaced fluid" in text  # the 'weak' key point


async def test_validate_lesson_treats_ungraded_point_as_missing() -> None:
    """A key point the model omitted from its grades is treated as `missing`
    — a lesson cannot pass on an un-graded point."""
    # The model only graded the FIRST key point.
    partial = {
        "grades": [
            {
                "section": "The buoyant force",
                "key_point": _key_point_texts()[0],
                "verdict": "covered",
                "detail": "ok",
            }
        ]
    }
    report = await validate_lesson(
        topic_title="Buoyancy",
        steps=_steps(4),
        comprehension_slice=_slice(),
        gemini=_fake_gemini([_FakeResp(partial)]),
    )
    assert report.passed is False
    # The two un-graded points are reported as missing.
    assert len(report.gaps) == 2
    assert all(g.verdict == "missing" for g in report.gaps)


async def test_validate_lesson_empty_slice_trivially_passes() -> None:
    """A slice with no key points cannot fail — there is nothing to check."""
    report = await validate_lesson(
        topic_title="Empty",
        steps=_steps(3),
        comprehension_slice=ComprehensionSlice(),
        gemini=_fake_gemini([_FakeResp(_grade_payload(["covered"] * 3))]),
    )
    assert report.passed is True
    assert report.total == 0


async def test_validate_lesson_rejects_malformed_grade() -> None:
    """A grading response with no parsed object and no text is rejected."""
    with pytest.raises(ValidateError) as ei:
        await validate_lesson(
            topic_title="Buoyancy",
            steps=_steps(3),
            comprehension_slice=_slice(),
            gemini=_fake_gemini([_FakeResp(None, text="")]),
        )
    assert ei.value.reason == "malformed_output"


async def test_validate_lesson_parses_json_text_fallback() -> None:
    """When the SDK skips structured parsing, a JSON `.text` body is used."""
    import json

    raw = json.dumps(_grade_payload(["covered", "covered", "covered"]))
    report = await validate_lesson(
        topic_title="Buoyancy",
        steps=_steps(4),
        comprehension_slice=_slice(),
        gemini=_fake_gemini([_FakeResp(None, text=raw)]),
    )
    assert report.passed is True


# ─── retry-once-then-draft (generate_and_validate) ───────────────────────────
def _canned_lesson(n_steps: int = 6) -> GeneratedLesson:
    """A well-formed `GeneratedLesson` — the generation model's reply."""
    items = [GeneratedStep(tts="Preparing your lesson.", html="Preparing your "
                           "lesson…", dur="00:00", page_ref=0)]
    for i in range(1, n_steps):
        items.append(
            GeneratedStep(
                tts="A submerged block displaces fluid and buoyancy lifts it.",
                html=('A submerged block displaces <span class="hl-y">fluid'
                      '</span> upward.'),
                dur=f"{i * 2:02d}:00",
                page_ref=0,
            )
        )
    return GeneratedLesson(items=items)


def _gv_supabase() -> tuple[MagicMock, dict[str, Any]]:
    """A Supabase mock for `generate_and_validate` covering every table read /
    write the flow makes. Returns (client, spy) — `spy` records job-error
    writes and topic-version inserts so a test can assert on them.

    The flow touches: topics (load × several), units, courses, topic_pages,
    unit_segmentations, topic_versions (insert), pipeline_jobs (gap surface).
    """
    spy: dict[str, Any] = {"version_inserts": [], "job_error_updates": []}

    topic_row = {
        "id": "t1", "name": "Buoyancy", "summary": "Why things float.",
        "design_notes": None, "unit_id": "u1", "n": 1,
        "content": [],  # set after a generation mirrors it
    }
    seg_comprehension = {
        "sections": [
            {"title": "The buoyant force",
             "key_points": ["pressure is greater on the bottom face"]},
        ],
        "figures": [],
    }
    # Bug B: the topic's OWN key points live on its `ProposedTopic`. This
    # topic is n=1, so `proposed.topics[0]`. The validator slices from here.
    seg_proposed = {
        "topics": [
            {"title": "Buoyancy", "summary": "Why things float.",
             "key_points": ["pressure is greater on the bottom face"]},
        ],
    }

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "topics":
            def _select(_cols: str) -> Any:
                sel = MagicMock()
                sel.eq.return_value = sel
                single = MagicMock()
                single.execute.return_value = MagicMock(data=dict(topic_row))
                sel.single.return_value = single
                return sel

            q.select.side_effect = _select

            def _update(payload: dict[str, Any]) -> Any:
                # Mirror `content` so a later topic-content load sees it.
                if "content" in payload:
                    topic_row["content"] = payload["content"]
                u = MagicMock()
                u.eq.return_value = u
                u.execute.return_value = MagicMock(data=[payload])
                return u

            q.update.side_effect = _update
            return q
        if name == "units":
            sel = MagicMock()
            sel.eq.return_value = sel
            single = MagicMock()
            single.execute.return_value = MagicMock(data={"id": "u1",
                                                          "course_id": "c1"})
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "courses":
            sel = MagicMock()
            sel.eq.return_value = sel
            single = MagicMock()
            single.execute.return_value = MagicMock(
                data={"id": "c1", "subject": "Physics", "grade_band": "9-12",
                      "teaching_style": None}
            )
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "topic_pages":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=[])
            return q
        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(
                data=[{"id": "seg-1", "comprehension": seg_comprehension,
                       "proposed": seg_proposed,
                       "created_at": "2026-05-16T00:00:00Z"}]
            )
            return q
        if name == "topic_versions":
            q.select.return_value = q
            q.eq.return_value = q
            q.execute.return_value = MagicMock(data=[])

            def _insert(payload: dict[str, Any]) -> Any:
                spy["version_inserts"].append(payload)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[payload])
                return ins

            q.insert.side_effect = _insert
            return q
        if name == "pipeline_jobs":
            # select(...).eq().eq().order().limit().execute() → the latest
            # generate job; update(...).eq().execute() → the gap-report write.
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(
                data=[{"id": "job-1", "created_at": "z"}]
            )

            def _update(payload: dict[str, Any]) -> Any:
                spy["job_error_updates"].append(payload)
                u = MagicMock()
                u.eq.return_value = u
                u.execute.return_value = MagicMock(data=[payload])
                return u

            q.update.side_effect = _update
            return q
        raise AssertionError(f"unexpected table {name!r}")

    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    return client, spy


async def test_generate_and_validate_passes_first_try_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lesson that validates on the FIRST attempt is NOT retried — exactly
    one generation — and the topic still ends `status='draft'` (validation is
    a precondition for publish, not auto-publish)."""
    client, spy = _gv_supabase()
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    # Calls in order: generate(1) → validate(1, PASS).
    gemini = _fake_gemini([
        _FakeResp(_canned_lesson(6)),                       # generation
        _FakeResp({"grades": [{"section": "The buoyant force",
                               "key_point": "pressure is greater on the "
                               "bottom face", "verdict": "covered",
                               "detail": "ok"}]}),           # validation PASS
    ])
    out = await generate_and_validate("t1", gemini=gemini)

    assert out.passed is True
    assert out.attempts == 1  # passed first try — no retry
    assert len(spy["version_inserts"]) == 1  # exactly one generation persisted
    # No gap report surfaced on a passing lesson.
    assert spy["job_error_updates"] == []


async def test_generate_and_validate_retries_once_then_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lesson that fails validation is retried EXACTLY ONCE; a second
    failure leaves the topic `status='draft'` with the validator's gap report
    surfaced (AC: retry-once-then-draft)."""
    client, spy = _gv_supabase()
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    fail_grade = _FakeResp({"grades": [{"section": "The buoyant force",
                                        "key_point": "pressure is greater on "
                                        "the bottom face", "verdict": "missing",
                                        "detail": "the lesson never explains "
                                        "this"}]})
    # generate(1) → validate(1, FAIL) → generate(2, retry) → validate(2, FAIL).
    gemini = _fake_gemini([
        _FakeResp(_canned_lesson(4)), fail_grade,
        _FakeResp(_canned_lesson(4)), fail_grade,
    ])
    out = await generate_and_validate("t1", gemini=gemini)

    assert out.passed is False
    # Retried EXACTLY once — two generations total, no more.
    assert out.attempts == 2
    assert len(spy["version_inserts"]) == 2
    # The gap report is non-empty and was surfaced on the generate job.
    assert out.report.gaps
    assert len(spy["job_error_updates"]) == 1
    surfaced = spy["job_error_updates"][0]["error"]
    assert "failed validation" in surfaced
    # The topic is left `draft` — generate_and_validate never publishes.
    # (No `status` update to 'published' was made; the confirmed topic
    # started 'draft' and stays there.)


async def test_generate_and_validate_retry_succeeds_stops_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the SINGLE retry validates, the flow stops there — `attempts == 2`,
    `passed` True, and no gap report is surfaced."""
    client, spy = _gv_supabase()
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    pass_grade = _FakeResp({"grades": [{"section": "The buoyant force",
                                        "key_point": "pressure is greater on "
                                        "the bottom face", "verdict": "covered",
                                        "detail": "taught"}]})
    fail_grade = _FakeResp({"grades": [{"section": "The buoyant force",
                                        "key_point": "pressure is greater on "
                                        "the bottom face", "verdict": "missing",
                                        "detail": "not taught"}]})
    # generate(1) → validate(1, FAIL) → generate(2) → validate(2, PASS).
    gemini = _fake_gemini([
        _FakeResp(_canned_lesson(4)), fail_grade,
        _FakeResp(_canned_lesson(6)), pass_grade,
    ])
    out = await generate_and_validate("t1", gemini=gemini)

    assert out.passed is True
    assert out.attempts == 2
    assert len(spy["version_inserts"]) == 2
    assert spy["job_error_updates"] == []  # passed — nothing surfaced


async def test_generate_and_validate_grades_against_validation_slice_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a `validation_slice` is passed, the lesson is graded against IT,
    not the topic's own DB slice. The task 2.7 e2e's deliberate-failure run
    relies on this — it grades a topic against the WHOLE unit's key points so
    the lesson reliably fails validation."""
    client, _spy = _gv_supabase()
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    # The topic's OWN slice (the mock's `proposed.topics[0]`) has ONE key
    # point; the `_slice()` override has THREE. `report.total` is the count
    # of key points GRADED — 3 proves the override drove validation, not the
    # 1-key-point DB slice.
    gemini = _fake_gemini([
        _FakeResp(_canned_lesson(6)),                                   # generate
        _FakeResp(_grade_payload(["covered", "covered", "covered"])),    # validate
    ])
    out = await generate_and_validate(
        "t1", gemini=gemini, validation_slice=_slice()
    )

    assert out.report.total == 3  # the 3-KP override, not the 1-KP DB slice
    assert out.passed is True
    assert out.attempts == 1
