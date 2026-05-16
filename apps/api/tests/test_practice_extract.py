"""Tests for worksheet question extraction — the practice-quiz source (2.8).

All tests run offline:
  • Gemini is stubbed — `extract_practice_questions` / `extract_unit_practice`
    are given a fake `GeminiService` whose `generate_from_pdfs` returns a
    canned `_ExtractedWorksheet` (per material, when more than one is asked).
  • Supabase is a `MagicMock` modelling the `unit_segmentations` +
    `lesson_materials` reads and the `lesson-materials` Storage download.

Covers the `docs/task-execution.md` 2.8 acceptance criteria:
  1. a unit with a practice worksheet yields structured MCQs tagged to the
     right (material_idx, page_idx, question_label) — directly consumable by
     `generate_quiz`'s practice path;
  2. a topic with `quiz_source='practice'` builds its quiz from them (the
     consumer test feeds the emitted `PracticeQuestion`s to `generate_quiz`);
  3. a question with no clear answer key is FLAGGED, not invented.

Plus: an extractable MCQ that fails `QuizQuestion` validation becomes a
`FlaggedQuestion` (the run never crashes on one bad question); tags spanning
two materials are grouped into the right per-material calls; the DB wrapper
raises `ExtractError('no_practice_tags')` when the segmentation has none.

The live verification is run by the orchestrator via
`app.pipeline.practice_extract_script`.
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

from app.pipeline.practice_extract import (  # noqa: E402
    ExtractError,
    FlaggedQuestion,
    PracticeExtractResult,
    _ExtractedQuestion,
    _ExtractedWorksheet,
    extract_practice_questions,
    extract_unit_practice,
)
from app.pipeline.quiz import PracticeQuestion, generate_quiz  # noqa: E402


# ─── helpers ─────────────────────────────────────────────────────────────────
def _good_question(
    label: str = "Q1",
    page_idx: int = 0,
    prompt: str = "Why does a submerged block feel an upward push from the "
    "water around it?",
) -> _ExtractedQuestion:
    """A well-formed, extractable `_ExtractedQuestion` (answer key in material)."""
    return _ExtractedQuestion(
        question_label=label,
        page_idx=page_idx,
        extractable=True,
        prompt=prompt,
        choices=[
            "Pressure is greater on its lower face than its upper face.",
            "The water above it weighs nothing at all.",
            "Gravity pushes upward inside any fluid.",
            "The block creates its own magnetic field.",
        ],
        correct_idx=0,
        explanation=(
            "Fluid pressure rises with depth, so the bottom face feels a "
            "larger force than the top — the net is the buoyant force."
        ),
    )


def _flagged_question(
    label: str = "Q2",
    page_idx: int = 0,
    reason: str = "no answer key in the material",
) -> _ExtractedQuestion:
    """A question the model declined to answer — no answer key in the material."""
    return _ExtractedQuestion(
        question_label=label,
        page_idx=page_idx,
        extractable=False,
        flag_reason=reason,
    )


def _worksheet(*questions: _ExtractedQuestion) -> _ExtractedWorksheet:
    """An `_ExtractedWorksheet` carrying `questions`."""
    return _ExtractedWorksheet(questions=list(questions))


def _fake_gemini(
    *worksheets: _ExtractedWorksheet,
    capture: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """A stub `GeminiService` whose `generate_from_pdfs` returns one canned
    `_ExtractedWorksheet` per call, in order.

    With a single worksheet it is returned for every call; with several the
    Nth call returns the Nth (so a 2-material extraction can be checked). When
    `capture` is given, each call's kwargs are appended to it.
    """
    svc = MagicMock(name="gemini")
    calls = {"n": 0}

    async def _gen(pdfs: list[bytes], prompt: str, **kwargs: Any) -> dict[str, Any]:
        idx = calls["n"]
        calls["n"] += 1
        if capture is not None:
            capture.append({"pdfs": pdfs, "prompt": prompt, **kwargs})
        ws = worksheets[idx] if idx < len(worksheets) else worksheets[-1]
        return {"text": "", "json": ws}

    svc.generate_from_pdfs = _gen
    return svc


def _tag(material_idx: int, page_idx: int, label: str, topic_idx: int = 0
         ) -> dict[str, Any]:
    """A §2.2 `practice_tag` dict."""
    return {
        "material_idx": material_idx,
        "page_idx": page_idx,
        "question_label": label,
        "topic_idx": topic_idx,
    }


# ─── core: AC 1 — a worksheet yields structured, correctly-tagged MCQs ───────
async def test_core_extracts_structured_mcqs_with_right_coordinates() -> None:
    """AC 1: the core turns well-formed model output into `PracticeQuestion`s
    that carry the correct (material_idx, page_idx, question_label)."""
    tags = [_tag(0, 2, "Q1"), _tag(0, 3, "Q5")]
    worksheet = _worksheet(
        _good_question("Q1", page_idx=2),
        _good_question("Q5", page_idx=3, prompt="What balances an object's "
                       "weight when it floats at rest on a fluid?"),
    )
    result = await extract_practice_questions(
        pdfs_by_material={0: b"%PDF-worksheet"},
        practice_tags=tags,
        gemini=_fake_gemini(worksheet),
    )
    assert isinstance(result, PracticeExtractResult)
    assert len(result.questions) == 2
    assert result.flagged == []
    pq = result.questions[0]
    assert isinstance(pq, PracticeQuestion)
    assert (pq.material_idx, pq.page_idx, pq.question_label) == (0, 2, "Q1")
    assert len(pq.question.choices) == 4
    assert 0 <= pq.question.correct_idx <= 3
    # The second carries its own coordinates.
    assert (result.questions[1].material_idx, result.questions[1].page_idx,
            result.questions[1].question_label) == (0, 3, "Q5")


async def test_core_runs_on_the_pro_model() -> None:
    """Worksheet extraction is quiz-related generation — it runs on the PRO
    slot (`model-strategy.md` §6)."""
    from app.core.config import settings

    capture: list[dict[str, Any]] = []
    await extract_practice_questions(
        pdfs_by_material={0: b"%PDF"},
        practice_tags=[_tag(0, 0, "Q1")],
        gemini=_fake_gemini(_worksheet(_good_question("Q1")), capture=capture),
    )
    assert capture[0]["model"] == settings.gemini_model_pro


# ─── core: AC 3 — flag, don't invent ─────────────────────────────────────────
async def test_core_flags_question_with_no_answer_key() -> None:
    """AC 3: a question the model marks `extractable=false` (no answer key in
    the material) becomes a `FlaggedQuestion`, NOT a `PracticeQuestion` — the
    answer is never invented."""
    worksheet = _worksheet(
        _good_question("Q1"),
        _flagged_question("Q2", reason="no answer key in the material"),
    )
    result = await extract_practice_questions(
        pdfs_by_material={0: b"%PDF"},
        practice_tags=[_tag(0, 0, "Q1"), _tag(0, 0, "Q2")],
        gemini=_fake_gemini(worksheet),
    )
    # Q1 extracted, Q2 flagged — not invented.
    assert [pq.question_label for pq in result.questions] == ["Q1"]
    assert len(result.flagged) == 1
    fq = result.flagged[0]
    assert isinstance(fq, FlaggedQuestion)
    assert (fq.material_idx, fq.page_idx, fq.question_label) == (0, 0, "Q2")
    assert "no answer key" in fq.reason


# ─── core: a bad MCQ is flagged, the run does not crash ──────────────────────
async def test_core_flags_extractable_question_that_fails_quiz_validation() -> None:
    """An `extractable=true` question whose MCQ violates the `QuizQuestion`
    contract (here: only 3 choices) becomes a `FlaggedQuestion` — the run does
    NOT crash on one bad question, and the rest still extract."""
    bad = _ExtractedQuestion(
        question_label="Q2",
        page_idx=1,
        extractable=True,
        prompt="A short but valid-length prompt about buoyancy and floating?",
        choices=["only", "three", "choices"],  # QuizQuestion requires exactly 4
        correct_idx=0,
        explanation="This explanation is comfortably long enough to validate.",
    )
    worksheet = _worksheet(_good_question("Q1"), bad)
    result = await extract_practice_questions(
        pdfs_by_material={0: b"%PDF"},
        practice_tags=[_tag(0, 0, "Q1"), _tag(0, 1, "Q2")],
        gemini=_fake_gemini(worksheet),
    )
    # The good one still extracted — the run survived the bad question.
    assert [pq.question_label for pq in result.questions] == ["Q1"]
    assert len(result.flagged) == 1
    fq = result.flagged[0]
    assert fq.question_label == "Q2"
    assert "quiz-schema validation" in fq.reason


# ─── core: tags spanning two materials -> one call per material ──────────────
async def test_core_groups_tags_into_per_material_calls() -> None:
    """Tags on two different materials are grouped into one extraction call
    per material — each call gets only that material's PDF and labels."""
    tags = [
        _tag(0, 0, "Q1"),
        _tag(1, 4, "Q2"),
        _tag(0, 1, "Q3"),
    ]
    # Material 0's worksheet returns Q1 + Q3; material 1's returns Q2.
    ws0 = _worksheet(
        _good_question("Q1", page_idx=0),
        _good_question("Q3", page_idx=1, prompt="A second valid worksheet "
                       "question about pressure and depth in a fluid?"),
    )
    ws1 = _worksheet(_good_question("Q2", page_idx=4,
                                    prompt="A worksheet question that lives "
                                    "on the other material entirely?"))
    capture: list[dict[str, Any]] = []
    result = await extract_practice_questions(
        pdfs_by_material={0: b"%PDF-zero", 1: b"%PDF-one"},
        practice_tags=tags,
        gemini=_fake_gemini(ws0, ws1, capture=capture),
    )
    # Exactly two calls — one per material, in material_idx order.
    assert len(capture) == 2
    assert capture[0]["pdfs"] == [b"%PDF-zero"]
    assert capture[1]["pdfs"] == [b"%PDF-one"]
    # Material 0's call asked for Q1 and Q3; material 1's asked for Q2.
    assert "Q1" in capture[0]["prompt"] and "Q3" in capture[0]["prompt"]
    assert "Q2" not in capture[0]["prompt"]
    assert "Q2" in capture[1]["prompt"]
    # All three extracted, each with its own material_idx.
    assert len(result.questions) == 3
    by_label = {pq.question_label: pq for pq in result.questions}
    assert by_label["Q1"].material_idx == 0
    assert by_label["Q3"].material_idx == 0
    assert by_label["Q2"].material_idx == 1


async def test_core_flags_tags_for_a_material_with_no_pdf() -> None:
    """A material that has tags but whose PDF was not supplied has every one
    of its tagged questions flagged — never silently dropped."""
    result = await extract_practice_questions(
        pdfs_by_material={},  # no PDFs at all
        practice_tags=[_tag(0, 0, "Q1"), _tag(0, 1, "Q2")],
        gemini=_fake_gemini(_worksheet(_good_question("Q1"))),
    )
    assert result.questions == []
    assert {fq.question_label for fq in result.flagged} == {"Q1", "Q2"}
    assert all("not available" in fq.reason for fq in result.flagged)


async def test_core_rejects_malformed_model_output() -> None:
    """Model output that does not parse into the extraction schema raises
    `ExtractError('malformed_output')` — a bad payload is never used."""
    svc = MagicMock(name="gemini")

    async def _gen(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"text": "", "json": None}

    svc.generate_from_pdfs = _gen
    with pytest.raises(ExtractError) as ei:
        await extract_practice_questions(
            pdfs_by_material={0: b"%PDF"},
            practice_tags=[_tag(0, 0, "Q1")],
            gemini=svc,
        )
    assert ei.value.reason == "malformed_output"


# ─── DB wrapper: extract_unit_practice ───────────────────────────────────────
def _extract_supabase(
    *,
    segmentations: list[dict[str, Any]] | None,
    materials: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock for `extract_unit_practice`.

    Models `unit_segmentations` (select.eq.order.limit.execute), the
    `lesson_materials` ordered read, and the `lesson-materials` Storage
    download (returns a stub PDF keyed by the `normalized_pdf` path).
    """

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(data=segmentations or [])
            return q
        if name == "lesson_materials":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=materials or [])
            return q
        raise AssertionError(f"unexpected table {name!r}")

    bucket = MagicMock(name="bucket")
    bucket.download.side_effect = lambda key: f"%PDF::{key}".encode()
    storage = MagicMock(name="storage")
    storage.from_.return_value = bucket
    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    client.storage = storage
    return client


def _seg(practice_tags: list[dict[str, Any]]) -> dict[str, Any]:
    """A `unit_segmentations` row whose proposed breakdown carries `tags`."""
    return {
        "id": "seg-1",
        "proposed": {"topics": [{"title": "Buoyancy"}],
                     "practice_tags": practice_tags},
        "created_at": "2026-05-16T00:00:00Z",
    }


async def test_db_wrapper_extracts_from_the_latest_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extract_unit_practice` loads the latest segmentation's practice_tags,
    downloads the tagged material's PDF, and returns the extracted MCQs."""
    seg = _seg([_tag(0, 0, "Q1"), _tag(0, 1, "Q2")])
    materials = [
        {"id": "m1", "filename": "worksheet.pdf",
         "normalized_pdf": "teacher/u1/m1/worksheet.pdf",
         "uploaded_at": "2026-05-16T00:00:00Z"},
    ]
    client = _extract_supabase(segmentations=[seg], materials=materials)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    worksheet = _worksheet(
        _good_question("Q1", page_idx=0),
        _good_question("Q2", page_idx=1, prompt="A second valid worksheet "
                       "question about why dense objects sink in water?"),
    )
    result = await extract_unit_practice("u1", gemini=_fake_gemini(worksheet))
    assert len(result.questions) == 2
    assert {pq.question_label for pq in result.questions} == {"Q1", "Q2"}
    assert all(pq.material_idx == 0 for pq in result.questions)


async def test_db_wrapper_raises_when_no_practice_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit whose latest segmentation has zero practice_tags cannot be
    extracted — `ExtractError('no_practice_tags')`."""
    client = _extract_supabase(segmentations=[_seg([])], materials=[])
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(ExtractError) as ei:
        await extract_unit_practice("u1", gemini=_fake_gemini(_worksheet()))
    assert ei.value.reason == "no_practice_tags"


async def test_db_wrapper_raises_when_no_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit with no `unit_segmentations` row cannot be extracted."""
    client = _extract_supabase(segmentations=[], materials=[])
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(ExtractError) as ei:
        await extract_unit_practice("u1", gemini=_fake_gemini(_worksheet()))
    assert ei.value.reason == "no_segmentation"


async def test_db_wrapper_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB wrapper reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    with pytest.raises(ExtractError) as ei:
        await extract_unit_practice("u1", gemini=_fake_gemini(_worksheet()))
    assert ei.value.reason == "no_supabase"


# ─── AC 2: the emitted PracticeQuestions feed generate_quiz's practice path ──
async def test_extracted_questions_feed_generate_quiz_practice_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 2: the `PracticeQuestion`s 2.8 emits are directly consumable by
    `generate_quiz(topic_id, practice_questions=...)` — the topic's tags match
    them on (material_idx, page_idx, question_label) and the quiz is built."""
    # 2.8 extracts three tagged worksheet questions for the unit.
    tags = [_tag(1, 0, "Q1"), _tag(1, 0, "Q2"), _tag(1, 1, "Q3")]
    worksheet = _worksheet(
        _good_question("Q1", page_idx=0),
        _good_question("Q2", page_idx=0, prompt="A worksheet question on what "
                       "happens to pressure as depth in a fluid increases?"),
        _good_question("Q3", page_idx=1, prompt="A worksheet question on why a "
                       "steel ship floats while a steel bar sinks fast?"),
    )
    extracted = await extract_practice_questions(
        pdfs_by_material={1: b"%PDF-worksheet"},
        practice_tags=tags,
        gemini=_fake_gemini(worksheet),
    )
    assert len(extracted.questions) == 3

    # Now generate_quiz on a 'practice' topic consumes exactly those.
    proposed = {
        "topics": [{"title": "Buoyancy"}],  # topic idx 0
        "practice_tags": tags,
    }
    inserts: list[dict[str, Any]] = []

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "topics":
            sel = MagicMock()
            sel.eq.return_value = sel
            single = MagicMock()
            single.execute.return_value = MagicMock(data={
                "id": "t1", "name": "Buoyancy", "quiz_source": "practice",
                "active_version_id": "ver-1", "unit_id": "u1",
            })
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(data=[{
                "id": "seg-1", "comprehension": {}, "proposed": proposed,
                "created_at": "2026-05-16T00:00:00Z",
            }])
            return q
        if name == "quiz_questions":
            def _delete() -> Any:
                d = MagicMock()
                d.eq.return_value = d
                d.execute.return_value = MagicMock(data=[])
                return d

            q.delete.side_effect = _delete

            def _insert(rows: list[dict[str, Any]]) -> Any:
                inserts.extend(rows)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=rows)
                return ins

            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    out = await generate_quiz("t1", practice_questions=extracted.questions)
    assert out.quiz_source == "practice"
    assert out.question_count == 3
    # The quiz is built from the teacher's own extracted worksheet questions.
    assert len(inserts) == 3
    assert inserts[0]["prompt"] == extracted.questions[0].question.prompt
