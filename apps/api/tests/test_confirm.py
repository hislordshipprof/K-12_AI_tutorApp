"""Tests for the confirm-the-breakdown step (task 2.7).

All tests run offline — Supabase is a `MagicMock` modelling the `topics` /
`topic_pages` / `unit_segmentations` / `lesson_materials` tables with REAL
insert/update/delete bookkeeping, so idempotency can be proven by running
`confirm_breakdown` twice against the same backing store.

Covers the `docs/task-execution.md` 2.7 acceptance criteria + the task's
required test cases:
  * `confirm_breakdown` materialises `topics` + `topic_pages` rows from the
    latest proposed breakdown;
  * confirmed topics start `status='draft'` (§4 — a teacher-course topic
    created by confirm starts draft);
  * it is IDEMPOTENT — a second confirm of the same breakdown UPDATES the
    existing rows and creates NO duplicates (§13).
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")

from app.pipeline.confirm import ConfirmError, confirm_breakdown  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# A stateful in-memory Supabase double — tracks `topics` + `topic_pages` rows
# so confirm_breakdown's idempotency is provable by running it twice.
# ─────────────────────────────────────────────────────────────────────────────
class _Store:
    """The backing tables for the confirm flow, with insert/update/delete."""

    def __init__(
        self,
        *,
        unit_id: str,
        proposed: dict[str, Any] | None,
        materials: list[dict[str, Any]],
        segmentations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.topics: list[dict[str, Any]] = []
        self.topic_pages: list[dict[str, Any]] = []
        self.materials = materials
        if segmentations is not None:
            self.segmentations = segmentations
        elif proposed is None:
            self.segmentations = []
        else:
            self.segmentations = [
                {"id": "seg-1", "proposed": proposed,
                 "created_at": "2026-05-16T00:00:00Z"}
            ]


def _fake_supabase(store: _Store) -> MagicMock:
    """Build a `MagicMock` Supabase client backed by `store`.

    Supports exactly the query shapes `confirm_breakdown` uses:
      • unit_segmentations: select.eq.order.limit.execute
      • lesson_materials:   select.eq.order.execute
      • topics:             select.eq.execute  /  insert.execute  /
                            update.eq.execute
      • topic_pages:        delete.eq.execute  /  insert.execute
    """

    def _table(name: str) -> Any:
        q = MagicMock(name=name)

        if name == "unit_segmentations":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.limit.return_value = q
            q.execute.return_value = MagicMock(data=list(store.segmentations))
            return q

        if name == "lesson_materials":
            q.select.return_value = q
            q.eq.return_value = q
            q.order.return_value = q
            q.execute.return_value = MagicMock(data=list(store.materials))
            return q

        if name == "topics":
            # select(...).eq("unit_id", ...).execute() → existing topics.
            def _select(_cols: str) -> Any:
                sel = MagicMock()
                sel.eq.return_value = sel
                sel.execute.return_value = MagicMock(
                    data=[dict(t) for t in store.topics]
                )
                return sel

            q.select.side_effect = _select

            def _insert(payload: dict[str, Any]) -> Any:
                row = dict(payload)
                row.setdefault("id", str(uuid.uuid4()))
                store.topics.append(row)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[row])
                return ins

            q.insert.side_effect = _insert

            def _update(payload: dict[str, Any]) -> Any:
                u = MagicMock()
                captured: dict[str, Any] = {}

                def _eq(col: str, val: Any) -> Any:
                    captured[col] = val
                    return u

                def _execute() -> Any:
                    for t in store.topics:
                        if t.get("id") == captured.get("id"):
                            t.update(payload)
                    return MagicMock(data=[payload])

                u.eq.side_effect = _eq
                u.execute.side_effect = _execute
                return u

            q.update.side_effect = _update
            return q

        if name == "topic_pages":
            def _delete() -> Any:
                d = MagicMock()
                captured: dict[str, Any] = {}

                def _eq(col: str, val: Any) -> Any:
                    captured[col] = val
                    return d

                def _execute() -> Any:
                    store.topic_pages[:] = [
                        p for p in store.topic_pages
                        if p.get("topic_id") != captured.get("topic_id")
                    ]
                    return MagicMock(data=[])

                d.eq.side_effect = _eq
                d.execute.side_effect = _execute
                return d

            q.delete.side_effect = _delete

            def _insert(payload: Any) -> Any:
                rows = payload if isinstance(payload, list) else [payload]
                store.topic_pages.extend(dict(r) for r in rows)
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=rows)
                return ins

            q.insert.side_effect = _insert
            return q

        raise AssertionError(f"unexpected table {name!r}")

    client = MagicMock(name="supabase")
    client.table.side_effect = _table
    return client


def _proposed(n_topics: int = 3) -> dict[str, Any]:
    """A proposed breakdown — `n_topics` topics, each with a 2-page set."""
    return {
        "topics": [
            {
                "title": f"Topic {i + 1}",
                "summary": f"summary of topic {i + 1}",
                "pages": [
                    {"material_idx": 0, "page_idx": 10 + i * 2},
                    {"material_idx": 0, "page_idx": 11 + i * 2},
                ],
            }
            for i in range(n_topics)
        ],
        "practice_tags": [],
        "empty_reason": None,
    }


_MATERIALS = [{"id": "mat-1", "uploaded_at": "2026-05-16T00:00:00Z"}]


# ─── confirm: materialise topics + topic_pages ───────────────────────────────
async def test_confirm_breakdown_materialises_topics_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first confirm creates one `topics` row per proposed topic and one
    `topic_pages` row per claimed page."""
    store = _Store(unit_id="u1", proposed=_proposed(3), materials=_MATERIALS)
    monkeypatch.setattr("app.core.supabase.get_supabase",
                        lambda: _fake_supabase(store))

    result = await confirm_breakdown("u1")

    assert len(result.topic_ids) == 3
    assert result.created == 3
    assert result.updated == 0
    # 3 topics × 2 pages each.
    assert result.page_count == 6
    assert len(store.topics) == 3
    assert len(store.topic_pages) == 6
    # Each topic_pages row points at the resolved material id.
    assert {p["material_id"] for p in store.topic_pages} == {"mat-1"}


async def test_confirm_breakdown_topics_start_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed teacher-course topics start `status='draft'` (§4) — even
    though the `topics.status` column default is 'published'."""
    store = _Store(unit_id="u1", proposed=_proposed(2), materials=_MATERIALS)
    monkeypatch.setattr("app.core.supabase.get_supabase",
                        lambda: _fake_supabase(store))

    await confirm_breakdown("u1")

    assert store.topics, "no topics were created"
    assert all(t["status"] == "draft" for t in store.topics)
    # The stable idempotency key — the unit-scoped 1-based ordinal `n`.
    assert sorted(t["n"] for t in store.topics) == [1, 2]


async def test_confirm_breakdown_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SECOND confirm of the same breakdown UPDATES the existing rows and
    creates NO duplicate `topics` / `topic_pages` (§13 — the double-submit
    case). This is the core acceptance criterion."""
    store = _Store(unit_id="u1", proposed=_proposed(3), materials=_MATERIALS)
    client = _fake_supabase(store)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    first = await confirm_breakdown("u1")
    assert first.created == 3 and first.updated == 0
    topic_ids_first = list(first.topic_ids)
    assert len(store.topics) == 3
    assert len(store.topic_pages) == 6

    # Re-confirm the SAME breakdown.
    second = await confirm_breakdown("u1")

    # No new rows — the second call updated, did not insert.
    assert second.created == 0
    assert second.updated == 3
    assert len(store.topics) == 3, "confirm_breakdown duplicated topics"
    assert len(store.topic_pages) == 6, "confirm_breakdown duplicated topic_pages"
    # The SAME topic ids come back — the rows were reused, not replaced.
    assert second.topic_ids == topic_ids_first


async def test_confirm_breakdown_idempotent_with_edited_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-confirm after the breakdown was EDITED re-syncs in place — the
    topic at each position is updated (name/pages), still no duplicate rows."""
    store = _Store(unit_id="u1", proposed=_proposed(2), materials=_MATERIALS)
    client = _fake_supabase(store)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    await confirm_breakdown("u1")
    assert len(store.topics) == 2

    # The teacher renamed topic 1 and changed its page set, then re-confirms.
    edited = _proposed(2)
    edited["topics"][0]["title"] = "Renamed topic"
    edited["topics"][0]["pages"] = [{"material_idx": 0, "page_idx": 99}]
    store.segmentations = [
        {"id": "seg-2", "proposed": edited, "created_at": "2026-05-16T01:00:00Z"}
    ]

    result = await confirm_breakdown("u1")

    assert result.created == 0 and result.updated == 2
    assert len(store.topics) == 2  # still no duplicates
    renamed = next(t for t in store.topics if t["n"] == 1)
    assert renamed["name"] == "Renamed topic"
    # Topic 1's pages were rewritten to the single edited page.
    t1_pages = [p for p in store.topic_pages if p["topic_id"] == renamed["id"]]
    assert len(t1_pages) == 1
    assert t1_pages[0]["page_idx"] == 99


# ─── confirm: error paths ────────────────────────────────────────────────────
async def test_confirm_breakdown_no_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit with no `unit_segmentations` row cannot be confirmed."""
    store = _Store(unit_id="u1", proposed=None, materials=_MATERIALS)
    monkeypatch.setattr("app.core.supabase.get_supabase",
                        lambda: _fake_supabase(store))
    with pytest.raises(ConfirmError) as ei:
        await confirm_breakdown("u1")
    assert ei.value.reason == "no_segmentation"


async def test_confirm_breakdown_empty_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A segmentation whose proposed breakdown has no topics (§13 'nothing
    teachable') is rejected — there is nothing to materialise."""
    empty = {"topics": [], "practice_tags": [],
             "empty_reason": "nothing teachable found here"}
    store = _Store(unit_id="u1", proposed=empty, materials=_MATERIALS)
    monkeypatch.setattr("app.core.supabase.get_supabase",
                        lambda: _fake_supabase(store))
    with pytest.raises(ConfirmError) as ei:
        await confirm_breakdown("u1")
    assert ei.value.reason == "empty_breakdown"


async def test_confirm_breakdown_requires_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a Supabase client the DB function reports it honestly."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    with pytest.raises(ConfirmError) as ei:
        await confirm_breakdown("u1")
    assert ei.value.reason == "no_supabase"
