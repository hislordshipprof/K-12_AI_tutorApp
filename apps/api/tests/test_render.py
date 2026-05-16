"""Tests for the slide-rendering stage (task 2.3).

All tests run offline:
  • `pymupdf` rasterises an in-memory synthetic multi-page PDF — no network,
    no fixture-file dependency.
  • Supabase (`topic_pages` / `lesson_materials` / `material_pages` tables +
    the Storage bucket) is a `MagicMock`.

Covers the `docs/task-execution.md` 2.3 acceptance criteria + the task's
required test cases:
  * a slide/figure page renders to a VALID PNG;
  * a `material_pages` row is written with the Storage key;
  * rendering is idempotent — a second `render_topic` run does not
    re-render or duplicate;
  * a `topic_pages` row whose `role` is NOT slide/figure is not rendered
    (prose notes/practice never rasterise);
  * two topics sharing one page render that page exactly once.
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

import fitz  # noqa: E402 — PyMuPDF

from app.pipeline.render import (  # noqa: E402
    RenderError,
    render_pdf_pages,
    render_topic,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ─── helpers ─────────────────────────────────────────────────────────────────
def _make_pdf(pages: int) -> bytes:
    """Build a real `pages`-page PDF in memory via pymupdf — each page carries
    text so the rasterised PNG has actual content."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Slide page {i}")
    data = doc.tobytes()
    doc.close()
    return data


def _topic_pages_supabase(
    topic_rows: list[dict[str, Any]],
    materials: dict[str, str | None],
    pre_rendered: list[dict[str, Any]] | None = None,
) -> tuple[MagicMock, list[dict[str, Any]], MagicMock]:
    """Build a Supabase mock.

      * `topic_pages` select(...).eq("topic_id", ...) -> `topic_rows`.
      * `lesson_materials` select("normalized_pdf").eq("id", mid).single()
        -> {"normalized_pdf": materials[mid]}.
      * `material_pages` select(...).in_(...) -> `pre_rendered` (rows already
        rendered); `.upsert(...)` is spied into the returned `upserts` list.
      * Storage `download` returns a real multi-page PDF; `upload` is a spy.

    Returns (client, upserts-list, bucket).
    """
    upserts: list[dict[str, Any]] = []
    pre = pre_rendered or []

    def _table(name: str) -> Any:
        q = MagicMock(name=name)
        if name == "topic_pages":
            q.select.return_value = q
            q.eq.return_value = q
            q.execute.return_value = MagicMock(data=topic_rows)
            return q
        if name == "material_pages":
            q.select.return_value = q
            q.in_.return_value = q
            q.execute.return_value = MagicMock(data=pre)

            def _upsert(payload: dict[str, Any], **_kw: Any) -> Any:
                upserts.append(payload)
                u = MagicMock()
                u.execute.return_value = MagicMock(data=[payload])
                return u

            q.upsert.side_effect = _upsert
            return q
        if name == "lesson_materials":
            # select("normalized_pdf").eq("id", mid).single().execute()
            def _select(_cols: str) -> Any:
                sel = MagicMock(name="lm-select")

                def _eq(_col: str, mid: str) -> Any:
                    eqq = MagicMock(name="lm-eq")
                    single = MagicMock(name="lm-single")
                    single.execute.return_value = MagicMock(
                        data={"normalized_pdf": materials.get(mid)}
                    )
                    eqq.single.return_value = single
                    return eqq

                sel.eq.side_effect = _eq
                return sel

            q.select.side_effect = _select
            return q
        raise AssertionError(f"unexpected table {name!r}")

    bucket = MagicMock(name="bucket")
    bucket.download.return_value = _make_pdf(8)
    storage = MagicMock(name="storage")
    storage.from_.return_value = bucket
    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    client.storage = storage
    return client, upserts, bucket


# ─── core: render_pdf_pages ──────────────────────────────────────────────────
def test_render_pdf_pages_produces_valid_pngs() -> None:
    """A slide page rasterises to a valid PNG (acceptance criterion)."""
    pdf = _make_pdf(5)
    pngs = render_pdf_pages(pdf, [0, 2, 4])
    assert set(pngs) == {0, 2, 4}
    for png in pngs.values():
        assert png.startswith(_PNG_MAGIC)
        assert len(png) > 100


def test_render_pdf_pages_dedupes_indices() -> None:
    """Duplicate page indices render once — the result is keyed by page."""
    pdf = _make_pdf(3)
    pngs = render_pdf_pages(pdf, [1, 1, 1])
    assert set(pngs) == {1}


def test_render_pdf_pages_rejects_out_of_range_page() -> None:
    """A page index past the end of the PDF raises `RenderError('bad_page')`."""
    pdf = _make_pdf(2)
    with pytest.raises(RenderError) as ei:
        render_pdf_pages(pdf, [5])
    assert ei.value.reason == "bad_page"


def test_render_pdf_pages_empty_request() -> None:
    """No requested pages -> an empty result, no crash."""
    assert render_pdf_pages(_make_pdf(2), []) == {}


def test_render_pdf_pages_dpi_changes_size() -> None:
    """A higher DPI produces a larger PNG — the resolution knob is live."""
    pdf = _make_pdf(1)
    small = render_pdf_pages(pdf, [0], dpi=72)[0]
    large = render_pdf_pages(pdf, [0], dpi=200)[0]
    assert len(large) > len(small)


# ─── render_topic: DB function ───────────────────────────────────────────────
def test_render_topic_renders_slide_pages_and_writes_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed topic's slide/figure pages render to PNGs that land in the
    bucket, and a `material_pages` row is upserted with the Storage key."""
    topic_rows = [
        {"material_id": "mat-1", "page_idx": 2, "role": "slide"},
        {"material_id": "mat-1", "page_idx": 4, "role": "figure"},
    ]
    client, upserts, bucket = _topic_pages_supabase(
        topic_rows, {"mat-1": "teacher-uid/unit-1/mat-1/deck.pdf"}
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    result = asyncio.run(render_topic("topic-1"))

    assert sorted(result.rendered) == ["mat-1:2", "mat-1:4"]
    assert result.skipped == []
    # Two PNGs uploaded to the bucket.
    assert bucket.upload.call_count == 2
    for call in bucket.upload.call_args_list:
        key, body = call.args[0], call.args[1]
        # PNG key sits beside the material's PDF, under the teacher-uid prefix.
        assert key.startswith("teacher-uid/unit-1/mat-1/pages/")
        assert key.endswith(".png")
        assert body.startswith(_PNG_MAGIC)
    # A material_pages row per page, carrying the Storage key.
    assert len(upserts) == 2
    by_idx = {u["idx"]: u for u in upserts}
    assert set(by_idx) == {2, 4}
    for idx, row in by_idx.items():
        assert row["material_id"] == "mat-1"
        assert row["image_path"].endswith(f"pages/{idx}.png")


def test_render_topic_skips_non_slide_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `topic_pages` row whose role is not slide/figure is NOT rendered —
    prose notes/practice pages never rasterise (the §6 guarantee)."""
    topic_rows = [
        {"material_id": "mat-1", "page_idx": 1, "role": "slide"},
        {"material_id": "mat-1", "page_idx": 7, "role": "notes"},
        {"material_id": "mat-1", "page_idx": 6, "role": "practice"},
    ]
    client, upserts, bucket = _topic_pages_supabase(
        topic_rows, {"mat-1": "teacher-uid/unit-1/mat-1/deck.pdf"}
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    result = asyncio.run(render_topic("topic-1"))

    # Only the slide page rendered; the notes + practice pages did not.
    assert result.rendered == ["mat-1:1"]
    assert {u["idx"] for u in upserts} == {1}
    assert bucket.upload.call_count == 1


def test_render_topic_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page already in `material_pages` is skipped on a re-run — no
    re-render, no duplicate row, no error (the PK is (material_id, idx))."""
    topic_rows = [
        {"material_id": "mat-1", "page_idx": 2, "role": "slide"},
        {"material_id": "mat-1", "page_idx": 4, "role": "slide"},
    ]
    # page 2 was already rendered by an earlier run.
    client, upserts, bucket = _topic_pages_supabase(
        topic_rows,
        {"mat-1": "teacher-uid/unit-1/mat-1/deck.pdf"},
        pre_rendered=[{"material_id": "mat-1", "idx": 2}],
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    result = asyncio.run(render_topic("topic-1"))

    # Only the not-yet-rendered page 4 is rendered; page 2 is skipped.
    assert result.rendered == ["mat-1:4"]
    assert result.skipped == ["mat-1:2"]
    assert bucket.upload.call_count == 1
    assert {u["idx"] for u in upserts} == {4}


def test_render_topic_shared_page_renders_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two `topic_pages` rows claiming the SAME page render it exactly once —
    the distinct (material_id, page_idx) de-dupe (two topics, one page)."""
    topic_rows = [
        {"material_id": "mat-1", "page_idx": 3, "role": "slide"},
        {"material_id": "mat-1", "page_idx": 3, "role": "figure"},
    ]
    client, upserts, bucket = _topic_pages_supabase(
        topic_rows, {"mat-1": "teacher-uid/unit-1/mat-1/deck.pdf"}
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    result = asyncio.run(render_topic("topic-1"))

    assert result.rendered == ["mat-1:3"]
    assert bucket.upload.call_count == 1
    assert len(upserts) == 1


def test_render_topic_no_renderable_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic with only non-slide/figure `topic_pages` rows (or none at all)
    raises `RenderError('no_pages')` — nothing to render."""
    client, _upserts, _bucket = _topic_pages_supabase(
        [{"material_id": "mat-1", "page_idx": 0, "role": "notes"}],
        {"mat-1": "teacher-uid/unit-1/mat-1/deck.pdf"},
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    with pytest.raises(RenderError) as ei:
        asyncio.run(render_topic("topic-1"))
    assert ei.value.reason == "no_pages"


def test_render_topic_missing_normalized_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claimed material with no `normalized_pdf` cannot be rendered."""
    topic_rows = [{"material_id": "mat-1", "page_idx": 1, "role": "slide"}]
    client, _upserts, _bucket = _topic_pages_supabase(
        topic_rows, {"mat-1": None}
    )
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    import asyncio

    with pytest.raises(RenderError) as ei:
        asyncio.run(render_topic("topic-1"))
    assert ei.value.reason == "missing_pdf"


def test_render_topic_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB function reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)

    import asyncio

    with pytest.raises(RenderError) as ei:
        asyncio.run(render_topic("topic-1"))
    assert ei.value.reason == "no_supabase"
