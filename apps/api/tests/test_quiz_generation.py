"""Tests for version-scoped quiz generation (task 2.6).

All tests run offline:
  • Gemini is stubbed — the auto path's `QuizGenerator` is given a fake
    `GeminiService` whose `client.aio.models.generate_content` returns a
    canned `QuizSet`.
  • Supabase is a `MagicMock` (topic / unit_segmentations / topic_pages reads
    + the quiz_questions delete + insert).

Covers the `docs/task-execution.md` 2.6 acceptance criteria:
  1. a generated topic has a quiz tagged to its `active_version_id`;
  2. re-generation (after a NEW lesson version) writes a NEW version's quiz
     WITHOUT touching the old version's rows — old `quiz_attempts` stay valid;
  3. `quiz_source='practice'` is rejected when no practice material exists.

The live Fluids verification is run by the orchestrator via
`app.pipeline.quiz_script`.
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

from app.content.quiz_schema import QuizQuestion, QuizSet  # noqa: E402
from app.pipeline.generate import (  # noqa: E402
    ComprehensionSlice,
    SliceFigure,
    SliceSection,
)
from app.pipeline.quiz import (  # noqa: E402
    PracticeQuestion,
    QuizError,
    generate_quiz,
    generate_quiz_set,
    practice_quiz_set,
    practice_tags_for_topic,
)


# ─── helpers ─────────────────────────────────────────────────────────────────
def _slice() -> ComprehensionSlice:
    """A small comprehension slice — two sections, one figure."""
    return ComprehensionSlice(
        sections=[
            SliceSection(title="The buoyant force", key_points=["a", "b"]),
            SliceSection(title="Archimedes' principle", key_points=["c"]),
        ],
        figures=[SliceFigure(description="a submerged block with pressure arrows")],
    )


def _quiz_question(prompt: str = "Why does a submerged block feel an upward "
                   "push from the water around it?") -> QuizQuestion:
    """A well-formed `QuizQuestion`."""
    return QuizQuestion(
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


def _canned_quiz() -> QuizSet:
    """A well-formed 3-question `QuizSet`."""
    return QuizSet(
        items=[
            _quiz_question("What is the name of the net upward force on a "
                           "submerged object?"),
            _quiz_question("A block sinks slowly. What does that tell you "
                           "about the buoyant force on it?"),
            _quiz_question("Why does an object float when fully at rest on "
                           "the surface of a fluid?"),
        ]
    )


class _FakeResp:
    """A Gemini response stub carrying a parsed `QuizSet`."""

    def __init__(self, parsed: Any, text: str = "") -> None:
        self.parsed = parsed
        self.text = text
        self.usage_metadata = None


def _fake_gemini(parsed: Any, text: str = "", *, capture: dict | None = None
                 ) -> MagicMock:
    """A stub `GeminiService` whose `client.aio.models.generate_content`
    returns a `_FakeResp(parsed, text)`."""

    async def _generate_content(**kwargs: Any) -> Any:
        if capture is not None:
            capture.update(kwargs)
        return _FakeResp(parsed, text)

    models = MagicMock()
    models.generate_content = _generate_content
    aio = MagicMock()
    aio.models = models
    client = MagicMock()
    client.aio = aio
    svc = MagicMock(name="gemini")
    svc.client = client
    return svc


# ─── core: auto path ─────────────────────────────────────────────────────────
async def test_generate_quiz_set_auto_returns_validated_quizset() -> None:
    """The auto core reuses the existing QuizGenerator against the topic's
    comprehension slice and returns a validated 3-question `QuizSet`."""
    quiz = await generate_quiz_set(
        topic_title="Buoyancy",
        comprehension_slice=_slice(),
        gemini=_fake_gemini(_canned_quiz()),
    )
    assert isinstance(quiz, QuizSet)
    assert len(quiz.items) == 3
    for q in quiz.items:
        assert 0 <= q.correct_idx <= 3
        assert len(q.choices) == 4


async def test_generate_quiz_set_auto_uses_pro_model() -> None:
    """Auto quiz generation runs on the PRO slot — same model the Recommended
    quiz pipeline uses."""
    from app.core.config import settings

    capture: dict[str, Any] = {}
    await generate_quiz_set(
        topic_title="Buoyancy",
        comprehension_slice=_slice(),
        gemini=_fake_gemini(_canned_quiz(), capture=capture),
    )
    assert capture["model"] == settings.gemini_model_pro


async def test_generate_quiz_set_auto_feeds_comprehension_to_prompt() -> None:
    """The comprehension slice reaches the quiz prompt — questions probe the
    topic's own material, not unrelated trivia."""
    capture: dict[str, Any] = {}
    await generate_quiz_set(
        topic_title="Buoyancy",
        comprehension_slice=_slice(),
        gemini=_fake_gemini(_canned_quiz(), capture=capture),
    )
    prompt = capture["contents"]
    assert "buoyant force" in prompt
    assert "Archimedes' principle" in prompt


# ─── core: practice path ─────────────────────────────────────────────────────
def test_practice_tags_for_topic_filters_by_topic_idx() -> None:
    """`practice_tags_for_topic` keeps only the tags assessing the topic."""
    tags = [
        {"material_idx": 1, "page_idx": 0, "question_label": "Q1", "topic_idx": 0},
        {"material_idx": 1, "page_idx": 0, "question_label": "Q2", "topic_idx": 2},
        {"material_idx": 1, "page_idx": 1, "question_label": "Q3", "topic_idx": 0},
        {"material_idx": 1, "page_idx": 1, "question_label": "Q4", "topic_idx": -1},
    ]
    mine = practice_tags_for_topic(tags, topic_idx=0)
    assert [t["question_label"] for t in mine] == ["Q1", "Q3"]


def test_practice_quiz_set_builds_from_teacher_questions() -> None:
    """The practice core emits the teacher's own questions unchanged — no
    model call, the quiz IS the teacher's worksheet."""
    pqs = [
        PracticeQuestion(
            material_idx=1, page_idx=0, question_label=f"Q{i}",
            question=_quiz_question(f"Practice question number {i} about "
                                    "buoyancy?"),
        )
        for i in range(1, 5)
    ]
    quiz = practice_quiz_set(pqs)
    # QuizSet requires exactly 3 — the first 3 tagged questions are taken.
    assert len(quiz.items) == 3
    assert quiz.items[0].prompt == pqs[0].question.prompt


# ─── generate_quiz: DB function — version scoping + the practice guard ───────
def _quiz_supabase(
    *,
    topic: dict[str, Any] | None,
    segmentations: list[dict[str, Any]] | None = None,
    topic_pages: list[dict[str, Any]] | None = None,
) -> tuple[MagicMock, list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a Supabase mock for `generate_quiz`.

    Returns (client, quiz_questions-inserts, quiz_questions-deletes). Each
    delete records the `(topic_id, topic_version_id)` it was scoped to.
    """
    inserts: list[dict[str, Any]] = []
    deletes: list[dict[str, Any]] = []

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "topics":
            sel = MagicMock()
            sel.eq.return_value = sel
            single = MagicMock()
            single.execute.return_value = MagicMock(data=topic)
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(data=segmentations or [])
            return q
        if name == "topic_pages":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=topic_pages or [])
            return q
        if name == "quiz_questions":
            # delete(...).eq(topic_id).eq(topic_version_id).execute()
            def _delete() -> Any:
                d = MagicMock()
                scope: dict[str, Any] = {}
                deletes.append(scope)

                def _eq(col: str, val: Any) -> Any:
                    scope[col] = val
                    return d

                d.eq.side_effect = _eq
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
    return client, inserts, deletes


def _seg(
    *,
    proposed: dict[str, Any] | None = None,
    created_at: str = "2026-05-16T00:00:00Z",
) -> dict[str, Any]:
    """A `unit_segmentations` row with a small comprehension."""
    return {
        "id": "seg-1",
        "comprehension": {
            "sections": [{"title": "Buoyant force", "key_points": ["x"]}],
            "figures": [],
        },
        "proposed": proposed or {"topics": [], "practice_tags": []},
        "created_at": created_at,
    }


# ── AC 1: a generated topic has a quiz tagged to its version ─────────────────
async def test_generate_quiz_auto_tags_rows_to_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 1: `generate_quiz` writes `quiz_questions` rows each carrying
    `topic_version_id = topics.active_version_id`."""
    client, inserts, _deletes = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "auto",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg()],
        topic_pages=[],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    out = await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))

    assert out.quiz_source == "auto"
    assert out.topic_version_id == "ver-1"
    assert out.question_count == 3
    assert len(inserts) == 3
    # EVERY row is tagged to the topic's active version.
    for i, row in enumerate(inserts):
        assert row["topic_id"] == "t1"
        assert row["topic_version_id"] == "ver-1"
        assert row["idx"] == i
        assert len(row["choices"]) == 4


async def test_generate_quiz_requires_an_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quiz versions with a lesson — a topic with no `active_version_id`
    cannot be quizzed (generate the lesson first, task 2.5)."""
    client, _i, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "auto",
            "active_version_id": None, "unit_id": "u1",
        },
        segmentations=[_seg()],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_active_version"


# ── AC 2: re-generation writes a NEW version's quiz, old rows untouched ──────
async def test_regeneration_targets_only_the_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 2: after a new lesson version, re-running `generate_quiz` tags the
    fresh quiz to the NEW `active_version_id` and the delete is scoped to
    THAT version only — a prior version's `quiz_questions` (and the
    `quiz_attempts` bound to them) are left untouched."""
    # First generate — active version is ver-1.
    client1, inserts1, deletes1 = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "auto",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg()],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client1)
    out1 = await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert out1.topic_version_id == "ver-1"
    assert all(r["topic_version_id"] == "ver-1" for r in inserts1)

    # Re-generate after task 2.5 produced a NEW lesson version — ver-2.
    client2, inserts2, deletes2 = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "auto",
            "active_version_id": "ver-2", "unit_id": "u1",
        },
        segmentations=[_seg()],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client2)
    out2 = await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))

    # The new set is tagged to ver-2.
    assert out2.topic_version_id == "ver-2"
    assert all(r["topic_version_id"] == "ver-2" for r in inserts2)
    # The delete that cleared room for the new set was scoped to ver-2 — it
    # cannot have removed ver-1's rows (so old quiz_attempts stay valid).
    assert len(deletes2) == 1
    assert deletes2[0]["topic_id"] == "t1"
    assert deletes2[0]["topic_version_id"] == "ver-2"


# ── AC 3: practice is rejected when no practice material exists ──────────────
async def test_practice_rejected_when_no_practice_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 3: `quiz_source='practice'` on a topic the unit has NO practice
    material for is rejected — `QuizError('no_practice_material')`."""
    proposed = {
        "topics": [{"title": "Buoyancy"}],  # this topic, idx 0
        "practice_tags": [],  # ...but no practice questions tagged anywhere
    }
    client, inserts, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "practice",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg(proposed=proposed)],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_practice_material"
    # Nothing was written — a rejected practice topic produces no quiz rows.
    assert inserts == []


async def test_practice_rejected_when_topic_not_in_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`practice` on a topic that cannot be located in the proposed breakdown
    cannot have its tags resolved — rejected as no practice material."""
    proposed = {
        "topics": [{"title": "Some other topic"}],
        "practice_tags": [
            {"material_idx": 1, "page_idx": 0, "question_label": "Q1",
             "topic_idx": 0},
        ],
    }
    client, _i, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "practice",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg(proposed=proposed)],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_practice_material"


async def test_practice_rejected_when_fewer_than_three_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`practice` with fewer than 3 usable tagged questions is rejected — the
    quiz contract is 3 questions, a 1-question worksheet cannot fill it."""
    proposed = {
        "topics": [{"title": "Buoyancy"}],
        "practice_tags": [
            {"material_idx": 1, "page_idx": 0, "question_label": "Q1",
             "topic_idx": 0},
        ],
    }
    client, _i, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "practice",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg(proposed=proposed)],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    only_one = [
        PracticeQuestion(material_idx=1, page_idx=0, question_label="Q1",
                         question=_quiz_question())
    ]
    with pytest.raises(QuizError) as ei:
        await generate_quiz(
            "t1", gemini=_fake_gemini(_canned_quiz()),
            practice_questions=only_one,
        )
    assert ei.value.reason == "no_practice_material"


async def test_practice_path_writes_teacher_questions_tagged_to_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic WITH practice material builds the quiz from the teacher's own
    questions and still tags every row to the active version."""
    proposed = {
        "topics": [{"title": "Buoyancy"}],
        "practice_tags": [
            {"material_idx": 1, "page_idx": 0, "question_label": f"Q{i}",
             "topic_idx": 0}
            for i in range(1, 4)
        ],
    }
    client, inserts, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "practice",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[_seg(proposed=proposed)],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    pqs = [
        PracticeQuestion(
            material_idx=1, page_idx=0, question_label=f"Q{i}",
            question=_quiz_question(f"Teacher worksheet question {i} on "
                                    "buoyancy and floating?"),
        )
        for i in range(1, 4)
    ]
    out = await generate_quiz(
        "t1", gemini=_fake_gemini(_canned_quiz()), practice_questions=pqs,
    )
    assert out.quiz_source == "practice"
    assert out.question_count == 3
    assert len(inserts) == 3
    for row in inserts:
        assert row["topic_version_id"] == "ver-1"
        assert row["provenance"]["source"] == "practice"
    # The persisted prompts are the teacher's own worksheet questions.
    assert inserts[0]["prompt"] == pqs[0].question.prompt


# ── failure modes ────────────────────────────────────────────────────────────
async def test_generate_quiz_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic id with no `topics` row is reported honestly."""
    client, _i, _d = _quiz_supabase(topic=None)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("missing", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_topic"


async def test_generate_quiz_no_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic whose unit has no `unit_segmentations` cannot be quizzed —
    there is no comprehension to slice."""
    client, _i, _d = _quiz_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "quiz_source": "auto",
            "active_version_id": "ver-1", "unit_id": "u1",
        },
        segmentations=[],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_segmentation"


async def test_generate_quiz_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB function reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    with pytest.raises(QuizError) as ei:
        await generate_quiz("t1", gemini=_fake_gemini(_canned_quiz()))
    assert ei.value.reason == "no_supabase"
