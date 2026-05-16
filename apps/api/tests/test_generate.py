"""Tests for per-topic lesson generation + scene assignment (task 2.5).

All tests run offline:
  • Gemini is stubbed — `generate_lesson`/`generate_topic` are given a fake
    `GeminiService` whose `client.aio.models.generate_content` returns a
    canned multi-step lesson.
  • Supabase is a `MagicMock` (topic / unit / course / topic_pages /
    unit_segmentations reads + the topic_versions insert + topics update).

Covers the `docs/task-execution.md` 2.5 acceptance criteria + the task's
required test cases:
  * steps parse to the `{tts, html, dur, scene, page?}` shape;
  * EVERY step has a non-empty `scene`;
  * a slide-backed step's `page` is one of the input `topic_pages` ids;
  * a step with no slide has no/null `page`;
  * depth is NOT hard-capped at 8 (a 12-step lesson generates);
  * `generate_topic` writes a `topic_versions` row, sets `active_version_id`,
    and mirrors `topics.content` (the §4 invariant);
  * malformed model output is rejected.

The live Fluids verification is run by the orchestrator via
`app.pipeline.generate_script`.
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

from app.agents.prompts import ARIA_BASE_PERSONA  # noqa: E402
from app.pipeline.generate import (  # noqa: E402
    ComprehensionSlice,
    GeneratedLesson,
    GeneratedStep,
    GenerateError,
    SliceFigure,
    SliceSection,
    TopicPage,
    generate_lesson,
    generate_topic,
    slice_comprehension,
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


def _pages(n: int = 2) -> list[TopicPage]:
    """`n` claimed `topic_pages` rows with stable ids."""
    return [
        TopicPage(id=f"page-{i}", material_idx=0, page_idx=10 + i, role="slide",
                  ord=i)
        for i in range(n)
    ]


def _canned_lesson(
    n_steps: int = 6,
    *,
    page_refs: list[int] | None = None,
    physics: bool = True,
) -> GeneratedLesson:
    """A well-formed `GeneratedLesson` of `n_steps` steps.

    `page_refs` overrides the per-step `page_ref` values (1-based, 0 =
    chalkboard); defaults to alternating 1 / 0. `physics` chooses step text
    that the typed `scene_tagger` will / won't match.
    """
    refs = page_refs if page_refs is not None else [
        (1 if i % 2 else 0) for i in range(n_steps)
    ]
    items: list[GeneratedStep] = [
        GeneratedStep(
            tts="Preparing your lesson.",
            html="Preparing your lesson…",
            dur="00:00",
            page_ref=0,
        )
    ]
    for i in range(1, n_steps):
        mm = i * 2
        if physics:
            tts = "A submerged block displaces fluid and the buoyancy lifts it."
            html = ('A submerged block displaces <span class="hl-y">fluid'
                    '</span> and buoyancy lifts it.')
        else:
            tts = "Photosynthesis turns sunlight into stored chemical energy."
            html = ('Plants use <span class="hl-g">photosynthesis</span> to '
                    'store energy.')
        items.append(
            GeneratedStep(
                tts=tts,
                html=html,
                dur=f"{mm:02d}:00",
                page_ref=refs[i] if i < len(refs) else 0,
            )
        )
    return GeneratedLesson(items=items)


class _FakeResp:
    """A Gemini response stub carrying a parsed `GeneratedLesson`."""

    def __init__(self, parsed: Any, text: str = "") -> None:
        self.parsed = parsed
        self.text = text
        self.usage_metadata = None


def _fake_gemini(parsed: Any, text: str = "", *, capture: dict | None = None
                 ) -> MagicMock:
    """A stub `GeminiService` whose `client.aio.models.generate_content`
    returns a `_FakeResp(parsed, text)`. `capture`, if given, records the
    kwargs of the call (so a test can assert the model / config)."""

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


# ─── core: step shape + scene assignment ─────────────────────────────────────
async def test_generate_lesson_produces_step_shape() -> None:
    """Generated steps parse to the `{tts, html, dur, scene, page?}` shape."""
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(2),
        gemini=_fake_gemini(_canned_lesson(6)),
    )
    assert len(steps) == 6
    for s in steps:
        c = s.to_content()
        assert set(c) >= {"tts", "html", "dur", "scene"}
        assert isinstance(c["tts"], str) and c["tts"]
        assert isinstance(c["html"], str) and c["html"]
        assert isinstance(c["dur"], str)


async def test_generate_lesson_every_step_has_a_scene() -> None:
    """EVERY step ends with a non-empty `scene` — the typed registry, a
    custom-svg fallback, or the text-board fallback. Never null."""
    # No scene_drawer is wired, and the step text below is non-physics so the
    # typed `scene_tagger` does NOT match — every step must still fall back to
    # a (non-empty) text-board scene.
    steps = await generate_lesson(
        topic_title="Photosynthesis",
        topic_summary="How plants make food.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Biology",
        grade_band="6-8",
        teaching_style=None,
        topic_pages=_pages(2),
        gemini=_fake_gemini(_canned_lesson(8, physics=False)),
    )
    for s in steps:
        assert s.scene, "a step has no scene"
        assert isinstance(s.scene, dict)
        assert s.scene.get("type"), "a step's scene has no type"
    # With no typed match and no drawer, every body step is the text board.
    assert all(s.scene["type"] == "chalkboard" for s in steps)


async def test_generate_lesson_uses_typed_scene_registry() -> None:
    """A step whose text matches a typed scene gets that typed scene — the
    existing `scene_tagger` registry is reused as the first rung."""
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(2),
        gemini=_fake_gemini(_canned_lesson(6, physics=True)),
    )
    # The body steps mention "fluid pressure" / "buoyant" → the fluid-column
    # typed scene. (Step 0 is the boilerplate intro — no concept text.)
    body_scenes = {s.scene["type"] for s in steps[1:]}
    assert "fluid-column" in body_scenes


async def test_generate_lesson_claude_fallback_is_reused() -> None:
    """A step no typed scene fits uses the injected Claude-authored drawer —
    the existing `custom-svg` fallback mechanism, wired via `scene_drawer`."""
    drawn: list[str] = []

    async def _drawer(topic: str, step_text: str) -> dict[str, Any]:
        drawn.append(step_text)
        return {"title": "diagram", "elements": [{"el": "circle", "cx": 1}]}

    steps = await generate_lesson(
        topic_title="Photosynthesis",
        topic_summary="How plants make food.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Biology",
        grade_band="6-8",
        teaching_style=None,
        topic_pages=_pages(1),
        gemini=_fake_gemini(_canned_lesson(5, physics=False)),
        scene_drawer=_drawer,
    )
    # The drawer ran for the non-typed body steps; those steps got a
    # custom-svg scene.
    assert drawn, "the Claude scene fallback drawer was never called"
    custom = [s for s in steps if s.scene["type"] == "custom-svg"]
    assert custom, "no step received a custom-svg fallback scene"
    assert custom[0].scene["params"]["title"] == "diagram"


# ─── core: page assignment + chalkboard fallback ─────────────────────────────
async def test_generate_lesson_slide_backed_page_is_a_real_id() -> None:
    """A slide-backed step's `page` is one of the input `topic_pages` ids."""
    pages = _pages(2)
    valid_ids = {p.id for p in pages}
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=pages,
        # steps 1,3,5 → page_ref 1; steps 0,2,4 → 0 (chalkboard).
        gemini=_fake_gemini(_canned_lesson(6, page_refs=[0, 1, 0, 2, 0, 1])),
    )
    slide_backed = [s for s in steps if s.page is not None]
    assert slide_backed, "expected some slide-backed steps"
    for s in slide_backed:
        assert s.page in valid_ids
        # A slide-backed step serialises a `page` key.
        assert "page" in s.to_content()


async def test_generate_lesson_chalkboard_step_has_no_page() -> None:
    """A step with `page_ref` 0 has no/null `page` — chalkboard fallback."""
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(2),
        gemini=_fake_gemini(_canned_lesson(4, page_refs=[0, 0, 0, 0])),
    )
    for s in steps:
        assert s.page is None
        # A chalkboard step OMITS the `page` key entirely (§6).
        assert "page" not in s.to_content()


async def test_generate_lesson_out_of_range_page_ref_falls_back() -> None:
    """A `page_ref` past the end of the claimed-page list yields no `page` —
    the over-claimed step falls back to the chalkboard, never a bad id."""
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(2),  # only refs 1 and 2 are valid
        gemini=_fake_gemini(_canned_lesson(4, page_refs=[0, 9, 0, 7])),
    )
    assert all(s.page is None for s in steps)


# ─── core: depth scales — no 8-step cap ──────────────────────────────────────
async def test_generate_lesson_depth_is_not_capped_at_eight() -> None:
    """Depth scales with the material — a 12-step lesson generates cleanly;
    the old fixed 8-step rubric is dropped (no max_length on the schema)."""
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="Why things float.",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(2),
        gemini=_fake_gemini(_canned_lesson(12)),
    )
    assert len(steps) == 12  # > 8 — not hard-capped


def test_generated_lesson_schema_has_no_max_length() -> None:
    """The model output schema places NO upper bound on step count — a
    20-step lesson validates. (min_length=2 only blocks a degenerate one.)"""
    big = _canned_lesson(20)
    assert len(GeneratedLesson.model_validate(big.model_dump()).items) == 20
    with pytest.raises(Exception):  # min_length=2 — a one-step lesson fails
        GeneratedLesson(items=[GeneratedStep(tts="x", html="x", dur="00:00")])


# ─── core: malformed-output rejection ────────────────────────────────────────
async def test_generate_lesson_rejects_no_output() -> None:
    """A response with no parsed object and no text is rejected as malformed."""
    with pytest.raises(GenerateError) as ei:
        await generate_lesson(
            topic_title="X",
            topic_summary="x",
            comprehension_slice=_slice(),
            design_notes=None,
            subject=None,
            grade_band=None,
            teaching_style=None,
            topic_pages=[],
            gemini=_fake_gemini(None, text=""),
        )
    assert ei.value.reason == "malformed_output"


async def test_generate_lesson_rejects_schema_violation() -> None:
    """Model output that violates the step schema is rejected as malformed."""
    # A dict missing `items` entirely — fails GeneratedLesson validation.
    with pytest.raises(GenerateError) as ei:
        await generate_lesson(
            topic_title="X",
            topic_summary="x",
            comprehension_slice=_slice(),
            design_notes=None,
            subject=None,
            grade_band=None,
            teaching_style=None,
            topic_pages=[],
            gemini=_fake_gemini({"not_items": []}),
        )
    assert ei.value.reason == "malformed_output"


async def test_generate_lesson_parses_json_text_fallback() -> None:
    """When the SDK skips the parse step, a JSON `.text` body is validated."""
    raw = _canned_lesson(5).model_dump_json()
    steps = await generate_lesson(
        topic_title="Buoyancy",
        topic_summary="x",
        comprehension_slice=_slice(),
        design_notes=None,
        subject="Physics",
        grade_band="9-12",
        teaching_style=None,
        topic_pages=_pages(1),
        gemini=_fake_gemini(None, text=raw),
    )
    assert len(steps) == 5


# ─── core: persona + model wiring ────────────────────────────────────────────
async def test_generate_lesson_uses_pro_model_and_persona() -> None:
    """Generation calls the PRO model; the system prompt is the per-course
    persona (task 2.4 `build_persona`) — a teacher course is NOT the built-in
    physics persona."""
    from app.core.config import settings

    capture: dict[str, Any] = {}
    await generate_lesson(
        topic_title="Cells",
        topic_summary="x",
        comprehension_slice=_slice(),
        design_notes="Use lots of analogies.",
        subject="Biology",
        grade_band="6-8",
        teaching_style="warm and story-driven",
        topic_pages=_pages(1),
        gemini=_fake_gemini(_canned_lesson(4), capture=capture),
    )
    assert capture["model"] == settings.gemini_model_pro
    system = capture["config"]["system_instruction"]
    # A Biology / 6-8 course → not the hard-coded physics persona.
    assert system != ARIA_BASE_PERSONA
    assert "Biology" in system
    # The teaching style is layered in.
    assert "story-driven" in system
    # The teacher's design notes reach the user prompt.
    assert "analogies" in capture["contents"]


async def test_generate_lesson_recommended_course_keeps_physics_persona() -> None:
    """An all-None course (Recommended/OpenStax) keeps the built-in physics
    persona verbatim — `build_persona(None, None, None)` is unchanged."""
    capture: dict[str, Any] = {}
    await generate_lesson(
        topic_title="Oscillations",
        topic_summary="x",
        comprehension_slice=_slice(),
        design_notes=None,
        subject=None,
        grade_band=None,
        teaching_style=None,
        topic_pages=[],
        gemini=_fake_gemini(_canned_lesson(4), capture=capture),
    )
    system = capture["config"]["system_instruction"]
    assert system.startswith(ARIA_BASE_PERSONA)


# ─── slice_comprehension ─────────────────────────────────────────────────────
def test_slice_comprehension_filters_figures_by_claimed_pages() -> None:
    """The slice keeps only figures on the topic's claimed pages; sections
    (which carry no page index in §2.2) are all kept."""
    comprehension = {
        "sections": [
            {"title": "Density", "key_points": ["mass over volume"]},
            {"title": "Pressure", "key_points": ["force per area"]},
        ],
        "figures": [
            {"material_idx": 0, "page_idx": 10, "description": "claimed fig"},
            {"material_idx": 0, "page_idx": 99, "description": "other fig"},
        ],
    }
    sl = slice_comprehension(comprehension, claimed=[(0, 10)])
    assert len(sl.sections) == 2
    assert [f.description for f in sl.figures] == ["claimed fig"]


def test_slice_comprehension_handles_empty_comprehension() -> None:
    """An empty / missing comprehension yields an empty slice, no crash."""
    sl = slice_comprehension({}, claimed=[(0, 0)])
    assert sl.sections == []
    assert sl.figures == []


# ─── generate_topic: DB function — the §4 invariant ──────────────────────────
def _topic_supabase(
    *,
    topic: dict[str, Any] | None,
    unit: dict[str, Any] | None = None,
    course: dict[str, Any] | None = None,
    topic_pages: list[dict[str, Any]] | None = None,
    segmentations: list[dict[str, Any]] | None = None,
    existing_versions: list[dict[str, Any]] | None = None,
) -> tuple[MagicMock, list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a Supabase mock for `generate_topic`.

    Returns (client, topic_versions-inserts, topics-updates).
    """
    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "topics":
            # Two uses: select(...).eq(...).single().execute() for the load,
            # and update(...).eq(...).execute() for the §4 mirror.
            def _select(_cols: str) -> Any:
                sel = MagicMock()
                sel.eq.return_value = sel
                single = MagicMock()
                single.execute.return_value = MagicMock(data=topic)
                sel.single.return_value = single
                return sel

            q.select.side_effect = _select

            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
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
            single.execute.return_value = MagicMock(data=unit)
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "courses":
            sel = MagicMock()
            sel.eq.return_value = sel
            single = MagicMock()
            single.execute.return_value = MagicMock(data=course)
            sel.single.return_value = single
            q.select.return_value = sel
            return q
        if name == "topic_pages":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=topic_pages or [])
            return q
        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(data=segmentations or [])
            return q
        if name == "topic_versions":
            # select(...).eq(...).execute() → existing version rows;
            # insert(...).execute() → spied.
            q.select.return_value = q
            q.eq.return_value = q
            q.execute.return_value = MagicMock(data=existing_versions or [])

            def _insert(payload: dict[str, Any]) -> Any:
                inserts.append(payload)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[payload])
                return ins

            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    return client, inserts, updates


async def test_generate_topic_writes_version_and_mirrors_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`generate_topic` INSERTs a `topic_versions` row, points
    `topics.active_version_id` at it, AND mirrors the SAME content into
    `topics.content` — the §4 invariant
    `topics.content == topic_versions[active_version_id].content`."""
    client, inserts, updates = _topic_supabase(
        topic={
            "id": "t1", "name": "Buoyancy", "summary": "Why things float.",
            "design_notes": None, "unit_id": "u1",
        },
        unit={"id": "u1", "course_id": "c1"},
        course={"id": "c1", "subject": "Physics", "grade_band": "9-12",
                "teaching_style": None},
        topic_pages=[
            {"id": "tp-1", "material_id": "m1", "page_idx": 10, "role": "slide",
             "ord": 0},
        ],
        segmentations=[{
            "id": "seg-1",
            "comprehension": {
                "sections": [{"title": "Buoyant force", "key_points": ["x"]}],
                "figures": [],
            },
            "created_at": "2026-05-16T00:00:00Z",
        }],
        existing_versions=[],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    out = await generate_topic("t1", gemini=_fake_gemini(_canned_lesson(6)))

    # A topic_versions row was written.
    assert len(inserts) == 1
    version = inserts[0]
    assert version["topic_id"] == "t1"
    assert version["label"] == "v1"
    assert isinstance(version["content"], list) and len(version["content"]) == 6

    # topics was updated: active_version_id → the new row, content mirrored.
    assert len(updates) == 1
    upd = updates[0]
    assert upd["active_version_id"] == version["id"]
    # THE §4 INVARIANT — topics.content is byte-identical to the version's.
    assert upd["content"] == version["content"]
    assert out.version_id == version["id"]
    assert out.step_count == 6


async def test_generate_topic_version_label_increments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-generation appends a NEW version — the label counts up (v3 when
    two versions already exist)."""
    client, inserts, _updates = _topic_supabase(
        topic={"id": "t1", "name": "Buoyancy", "summary": "x",
               "design_notes": None, "unit_id": "u1"},
        unit={"id": "u1", "course_id": "c1"},
        course={"id": "c1", "subject": "Physics", "grade_band": "9-12",
                "teaching_style": None},
        topic_pages=[],
        segmentations=[{"id": "s1", "comprehension": {}, "created_at": "z"}],
        existing_versions=[{"id": "v-old-1"}, {"id": "v-old-2"}],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    out = await generate_topic("t1", gemini=_fake_gemini(_canned_lesson(4)))
    assert out.label == "v3"
    assert inserts[0]["label"] == "v3"


async def test_generate_topic_step_page_is_a_real_topic_pages_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slide-backed step in the persisted content references a real
    `topic_pages` row id (the AC: slide-backed steps reference a valid id)."""
    client, inserts, _updates = _topic_supabase(
        topic={"id": "t1", "name": "Buoyancy", "summary": "x",
               "design_notes": None, "unit_id": "u1"},
        unit={"id": "u1", "course_id": "c1"},
        course={"id": "c1", "subject": "Physics", "grade_band": "9-12",
                "teaching_style": None},
        topic_pages=[
            {"id": "tp-A", "material_id": "m1", "page_idx": 1, "role": "slide",
             "ord": 0},
            {"id": "tp-B", "material_id": "m1", "page_idx": 2, "role": "slide",
             "ord": 1},
        ],
        segmentations=[{"id": "s1", "comprehension": {}, "created_at": "z"}],
        existing_versions=[],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    await generate_topic(
        "t1",
        gemini=_fake_gemini(_canned_lesson(4, page_refs=[0, 1, 0, 2])),
    )
    content = inserts[0]["content"]
    page_ids = {s["page"] for s in content if "page" in s}
    assert page_ids, "no slide-backed step in the persisted content"
    assert page_ids <= {"tp-A", "tp-B"}


async def test_generate_topic_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic id with no `topics` row is reported honestly."""
    client, _i, _u = _topic_supabase(topic=None)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(GenerateError) as ei:
        await generate_topic("missing", gemini=_fake_gemini(_canned_lesson(4)))
    assert ei.value.reason == "no_topic"


async def test_generate_topic_no_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic whose unit has no `unit_segmentations` cannot be generated —
    there is no comprehension to slice."""
    client, _i, _u = _topic_supabase(
        topic={"id": "t1", "name": "X", "summary": "x", "design_notes": None,
               "unit_id": "u1"},
        unit={"id": "u1", "course_id": "c1"},
        course={"id": "c1", "subject": None, "grade_band": None,
                "teaching_style": None},
        topic_pages=[],
        segmentations=[],  # none
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    with pytest.raises(GenerateError) as ei:
        await generate_topic("t1", gemini=_fake_gemini(_canned_lesson(4)))
    assert ei.value.reason == "no_segmentation"


async def test_generate_topic_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB function reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    with pytest.raises(GenerateError) as ei:
        await generate_topic("t1", gemini=_fake_gemini(_canned_lesson(4)))
    assert ei.value.reason == "no_supabase"
