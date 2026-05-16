"""Tests for the comprehension + topic-segmentation stage (task 2.2).

All tests run offline:
  • Gemini is stubbed — `comprehend_unit`/`segment_unit` are given a fake
    `GeminiService` whose `generate_from_pdfs` returns a canned payload.
  • Supabase is a `MagicMock` (table reads + Storage download + the row insert).

Covered: response parsing, §4 schema validation, malformed-output rejection,
the `unit_segmentations` row write (`status='proposed'`), the
converted-materials-required guard, empty-breakdown handling, and the
model-escalation threshold. The live Fluids verification is run by the
orchestrator via `app.pipeline.segment_script`.
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

from app.core.config import settings  # noqa: E402
from app.pipeline import segment  # noqa: E402
from app.pipeline.segment import (  # noqa: E402
    Comprehension,
    MaterialRead,
    PageClass,
    PageRef,
    ProposedBreakdown,
    ProposedTopic,
    SegmentError,
    UnitSegmentation,
    choose_segment_model,
    comprehend_unit,
    segment_unit,
)

# A minimal real PDF — one page object so `_pdf_page_count` returns 1.
_ONE_PAGE_PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\ntrailer<<>>\n%%EOF"


# ─── helpers ─────────────────────────────────────────────────────────────────
def _canned_segmentation() -> UnitSegmentation:
    """A well-formed segmentation — 4 topics, one excluded title page."""
    return UnitSegmentation(
        comprehension=Comprehension(
            materials=[MaterialRead(material_idx=0, kind="slides", page_count=5)],
            sections=[],
            figures=[],
            pages=[
                PageClass(material_idx=0, page_idx=0, teach=False, reason="title page"),
                PageClass(material_idx=0, page_idx=1, teach=True, reason=""),
                PageClass(material_idx=0, page_idx=2, teach=True, reason=""),
                PageClass(material_idx=0, page_idx=3, teach=True, reason=""),
                PageClass(material_idx=0, page_idx=4, teach=True, reason=""),
            ],
        ),
        proposed=ProposedBreakdown(
            topics=[
                ProposedTopic(
                    title=f"8.{n} Topic",
                    summary="A fluids subtopic.",
                    key_points=[f"key point {n}a", f"key point {n}b"],
                    pages=[PageRef(material_idx=0, page_idx=n)],
                )
                for n in range(1, 5)
            ],
            practice_tags=[],
            empty_reason=None,
        ),
    )


def _fake_gemini(payload: Any) -> MagicMock:
    """A stub GeminiService whose `generate_from_pdfs` returns `payload`."""
    svc = MagicMock(name="gemini")

    async def _gen(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"text": "", "json": payload}

    svc.generate_from_pdfs = _gen
    return svc


# ─── core: response parsing ──────────────────────────────────────────────────
async def test_comprehend_unit_parses_structured_output() -> None:
    """A parsed `UnitSegmentation` from structured output passes straight
    through `comprehend_unit`."""
    seg = await comprehend_unit(
        [_ONE_PAGE_PDF],
        [{"filename": "fluids.pptx", "kind": "slides"}],
        gemini=_fake_gemini(_canned_segmentation()),
    )
    assert isinstance(seg, UnitSegmentation)
    assert len(seg.proposed.topics) == 4
    assert [t.title for t in seg.proposed.topics] == [
        "8.1 Topic", "8.2 Topic", "8.3 Topic", "8.4 Topic",
    ]


async def test_comprehend_unit_parses_json_dict() -> None:
    """A raw JSON dict (the coercion fallback) is validated into the schema."""
    payload = _canned_segmentation().model_dump()
    assert isinstance(payload, dict)
    seg = await comprehend_unit(
        [_ONE_PAGE_PDF],
        [{"filename": "fluids.pptx", "kind": "slides"}],
        gemini=_fake_gemini(payload),
    )
    assert len(seg.proposed.topics) == 4
    # Non-teaching title page excluded; the 4 teaching pages kept.
    assert sum(1 for p in seg.comprehension.pages if not p.teach) == 1


# ─── core: §4 schema validation + malformed-output rejection ─────────────────
async def test_comprehend_unit_rejects_no_json() -> None:
    """A response with no parseable JSON is rejected — no row, never written."""
    with pytest.raises(SegmentError) as ei:
        await comprehend_unit(
            [_ONE_PAGE_PDF],
            [{"filename": "x.pdf", "kind": "notes"}],
            gemini=_fake_gemini(None),
        )
    assert ei.value.reason == "malformed_output"


async def test_comprehend_unit_rejects_schema_violation() -> None:
    """Model output that violates the §4 schema is rejected as malformed."""
    bad = {"comprehension": {"materials": []}}  # missing `proposed` entirely
    with pytest.raises(SegmentError) as ei:
        await comprehend_unit(
            [_ONE_PAGE_PDF],
            [{"filename": "x.pdf", "kind": "notes"}],
            gemini=_fake_gemini(bad),
        )
    assert ei.value.reason == "malformed_output"


async def test_comprehend_unit_rejects_non_object_json() -> None:
    """A JSON array (not an object) is rejected — the schema is an object."""
    with pytest.raises(SegmentError) as ei:
        await comprehend_unit(
            [_ONE_PAGE_PDF],
            [{"filename": "x.pdf", "kind": "notes"}],
            gemini=_fake_gemini([1, 2, 3]),
        )
    assert ei.value.reason == "malformed_output"


async def test_comprehend_unit_requires_a_pdf() -> None:
    """No PDFs at all → `no_materials`."""
    with pytest.raises(SegmentError) as ei:
        await comprehend_unit([], [], gemini=_fake_gemini(_canned_segmentation()))
    assert ei.value.reason == "no_materials"


# ─── core: empty-breakdown handling ──────────────────────────────────────────
async def test_comprehend_unit_empty_breakdown() -> None:
    """An upload with no teachable content yields an empty breakdown WITH a
    reason — not invented topics (§13)."""
    empty = UnitSegmentation(
        comprehension=Comprehension(
            materials=[MaterialRead(material_idx=0, kind="notes", page_count=1)],
            pages=[PageClass(material_idx=0, page_idx=0, teach=False, reason="grades")],
        ),
        proposed=ProposedBreakdown(
            topics=[], practice_tags=[], empty_reason="nothing teachable found here"
        ),
    )
    seg = await comprehend_unit(
        [_ONE_PAGE_PDF],
        [{"filename": "grades.pdf", "kind": "notes"}],
        gemini=_fake_gemini(empty),
    )
    assert seg.proposed.topics == []
    assert seg.proposed.empty_reason == "nothing teachable found here"


# ─── core: per-topic key_points (Bug B) ──────────────────────────────────────
async def test_proposed_topic_carries_its_own_key_points() -> None:
    """Each proposed topic carries its OWN `key_points` — the teachable points
    THAT topic must cover (Bug B: the source of truth for lesson generation +
    validation, attributed per-topic, not unit-wide)."""
    seg = await comprehend_unit(
        [_ONE_PAGE_PDF],
        [{"filename": "fluids.pptx", "kind": "slides"}],
        gemini=_fake_gemini(_canned_segmentation()),
    )
    for n, t in enumerate(seg.proposed.topics, 1):
        assert t.key_points == [f"key point {n}a", f"key point {n}b"]
    # The field round-trips through model_dump (it rides inside `proposed`).
    dumped = seg.proposed.model_dump()
    assert dumped["topics"][0]["key_points"] == ["key point 1a", "key point 1b"]


def test_proposed_topic_key_points_defaults_empty() -> None:
    """`key_points` is additive — a topic without it still validates (the
    field defaults to an empty list)."""
    t = ProposedTopic(title="X", summary="x")
    assert t.key_points == []


def test_comprehension_prompt_asks_for_per_topic_key_points() -> None:
    """The comprehension prompt instructs the model to attribute each proposed
    topic its OWN key points (not the unit's)."""
    prompt = segment._build_comprehension_prompt(
        [{"filename": "f.pdf", "kind": "slides"}]
    )
    assert "key_points" in prompt
    # It is explicit that the points are per-topic, not unit-wide.
    assert "OWN" in prompt or "own" in prompt


# ─── core: model escalation threshold ────────────────────────────────────────
def test_choose_segment_model_default_is_flash() -> None:
    """A small deck stays on the segment (flash) model."""
    assert choose_segment_model(10) == settings.gemini_model_segment
    assert settings.gemini_model_segment == "gemini-3-flash-preview"


def test_choose_segment_model_escalates_on_large_deck() -> None:
    """A deck at/above the page threshold escalates to the PRO model."""
    below = settings.segment_escalate_pages - 1
    at = settings.segment_escalate_pages
    assert choose_segment_model(below) == settings.gemini_model_segment
    assert choose_segment_model(at) == settings.gemini_model_pro
    assert settings.gemini_model_pro == "gemini-3.1-pro-preview"


async def test_comprehend_unit_passes_chosen_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large combined deck makes `comprehend_unit` call Gemini with the
    escalated PRO model id."""
    seen: dict[str, Any] = {}

    svc = MagicMock(name="gemini")

    async def _gen(pdfs: list[bytes], prompt: str, **kwargs: Any) -> dict[str, Any]:
        seen["model"] = kwargs.get("model")
        return {"text": "", "json": _canned_segmentation()}

    svc.generate_from_pdfs = _gen
    # Force a high page count so escalation triggers regardless of the PDF.
    monkeypatch.setattr(segment, "_pdf_page_count", lambda _pdf: 999)

    await comprehend_unit(
        [_ONE_PAGE_PDF],
        [{"filename": "huge.pdf", "kind": "slides"}],
        gemini=svc,
    )
    assert seen["model"] == settings.gemini_model_pro


# ─── segment_unit: DB function ───────────────────────────────────────────────
def _materials_supabase(rows: list[dict[str, Any]]) -> tuple[MagicMock, list[Any]]:
    """Build a Supabase mock: `lesson_materials` select returns `rows`,
    Storage download returns a PDF, and `unit_segmentations` insert is spied.
    Returns (client, inserts-list)."""
    inserts: list[dict[str, Any]] = []

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "lesson_materials":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=rows)
            return q
        if name == "unit_segmentations":

            def _insert(payload: dict[str, Any]) -> Any:
                inserts.append(payload)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[payload])
                return ins

            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    bucket = MagicMock(name="bucket")
    bucket.download.return_value = _ONE_PAGE_PDF
    storage = MagicMock(name="storage")
    storage.from_.return_value = bucket
    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    client.storage = storage
    return client, inserts


async def test_segment_unit_writes_proposed_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`segment_unit` loads converted materials, comprehends, and INSERTs a
    `unit_segmentations` row with `status='proposed'`."""
    rows = [
        {
            "id": "m1",
            "kind": "slides",
            "filename": "fluids.pptx",
            "normalized_pdf": "teacher/u1/m1/fluids.pdf",
            "conversion_status": "converted",
            "uploaded_at": "2026-05-16T00:00:00Z",
        }
    ]
    client, inserts = _materials_supabase(rows)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    out = await segment_unit("u1", gemini=_fake_gemini(_canned_segmentation()))

    assert out.status == "proposed"
    assert out.topic_count == 4
    assert len(inserts) == 1
    row = inserts[0]
    assert row["unit_id"] == "u1"
    assert row["status"] == "proposed"
    assert "comprehension" in row and "proposed" in row
    assert len(row["proposed"]["topics"]) == 4


async def test_segment_unit_rejects_unconverted_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A material still `pending`/`converting` blocks segmentation (§13)."""
    rows = [
        {
            "id": "m1",
            "kind": "slides",
            "filename": "fluids.pptx",
            "normalized_pdf": None,
            "conversion_status": "converting",
            "uploaded_at": "2026-05-16T00:00:00Z",
        }
    ]
    client, inserts = _materials_supabase(rows)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    with pytest.raises(SegmentError) as ei:
        await segment_unit("u1", gemini=_fake_gemini(_canned_segmentation()))
    assert ei.value.reason == "not_converted"
    assert inserts == []  # nothing written on a rejected segment


async def test_segment_unit_rejects_unit_with_no_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit with no `lesson_materials` rows cannot be segmented (§13)."""
    client, inserts = _materials_supabase([])
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    with pytest.raises(SegmentError) as ei:
        await segment_unit("u1", gemini=_fake_gemini(_canned_segmentation()))
    assert ei.value.reason == "no_materials"
    assert inserts == []


async def test_segment_unit_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB function reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    with pytest.raises(SegmentError) as ei:
        await segment_unit("u1", gemini=_fake_gemini(_canned_segmentation()))
    assert ei.value.reason == "no_supabase"
