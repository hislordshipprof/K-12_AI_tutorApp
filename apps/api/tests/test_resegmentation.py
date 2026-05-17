"""Tests for the re-segmentation mapping flow (task 5.4, `teacher-authoring.md`
§13).

`apply_resegmentation` maps a unit's latest proposed breakdown onto its
EXISTING topics by the teacher's explicit choice — `add` a new draft topic,
`replace` an existing one (repoint + reset to draft), `retire` a topic
(hidden from new students), and KEEP everything else untouched. Nothing is
deleted; an invalid mapping raises `ConfirmError` before any mutation.

Supabase is mocked: `.table(name)` dispatches to a stateful `_Table` fake so
inserts / updates / deletes are observable.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipeline.confirm import ConfirmError, apply_resegmentation

UNIT_ID = "11111111-1111-1111-1111-111111111111"
MAT_ID = "22222222-2222-2222-2222-222222222222"
SEG_ID = "33333333-3333-3333-3333-333333333333"
T_PUB = "44444444-4444-4444-4444-444444444401"
T_DRAFT = "44444444-4444-4444-4444-444444444402"
VERSION_ID = "55555555-5555-5555-5555-555555555555"
OTHER_TOPIC = "99999999-9999-9999-9999-999999999999"


class _Table:
    """A stateful select / insert / update / delete fake with `.eq()`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._mode = "select"
        self._f: dict[str, Any] = {}
        self._payload: Any = None
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None

    def select(self, *_a: Any) -> "_Table":
        self._mode, self._f, self._order, self._limit = "select", {}, None, None
        return self

    def insert(self, payload: Any) -> "_Table":
        self._mode, self._payload = "insert", payload
        return self

    def update(self, payload: dict[str, Any]) -> "_Table":
        self._mode, self._payload, self._f = "update", payload, {}
        return self

    def delete(self) -> "_Table":
        self._mode, self._f = "delete", {}
        return self

    def eq(self, key: str, value: Any) -> "_Table":
        self._f[key] = value
        return self

    def order(self, col: str, desc: bool = False) -> "_Table":
        self._order = (col, desc)
        return self

    def limit(self, n: int) -> "_Table":
        self._limit = n
        return self

    def _match(self, r: dict[str, Any]) -> bool:
        return all(str(r.get(k)) == str(v) for k, v in self._f.items())

    def execute(self) -> MagicMock:
        if self._mode == "insert":
            items = (
                self._payload
                if isinstance(self._payload, list)
                else [self._payload]
            )
            out: list[dict[str, Any]] = []
            for it in items:
                row = dict(it)
                row.setdefault("id", str(uuid.uuid4()))
                self.rows.append(row)
                out.append(dict(row))
            return MagicMock(data=out)
        if self._mode == "update":
            hit = [r for r in self.rows if self._match(r)]
            for r in hit:
                r.update(self._payload)
            return MagicMock(data=[dict(r) for r in hit])
        if self._mode == "delete":
            self.rows = [r for r in self.rows if not self._match(r)]
            return MagicMock(data=[])
        rows = [dict(r) for r in self.rows if self._match(r)]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return MagicMock(data=rows)


def _proposed(*titles: str) -> dict[str, Any]:
    return {
        "topics": [
            {
                "title": t,
                "summary": f"{t} summary",
                "pages": [{"material_idx": 0, "page_idx": i}],
            }
            for i, t in enumerate(titles)
        ]
    }


def _make_sb(
    *,
    proposed: dict[str, Any],
    topics: list[dict[str, Any]],
) -> tuple[MagicMock, dict[str, _Table]]:
    """Build a Supabase mock; returns the client + the table fakes."""
    tables: dict[str, _Table] = {
        "unit_segmentations": _Table(
            [
                {
                    "id": SEG_ID,
                    "unit_id": UNIT_ID,
                    "proposed": proposed,
                    "created_at": "2026-05-17T00:00:00+00:00",
                }
            ]
        ),
        "lesson_materials": _Table(
            [{"id": MAT_ID, "unit_id": UNIT_ID, "uploaded_at": "2026-05-01"}]
        ),
        "topics": _Table(topics),
        "topic_pages": _Table([]),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: tables.get(name, _Table([]))
    return client, tables


def _run(monkeypatch: pytest.MonkeyPatch, sb: MagicMock, **kwargs: Any) -> Any:
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: sb)
    return asyncio.run(apply_resegmentation(UNIT_ID, **kwargs))


# ═══ add ══════════════════════════════════════════════════════════════════
def test_resegment_add_creates_a_new_draft_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An `add` decision inserts a brand-new draft topic after the unit's
    current topics — existing topics untouched."""
    sb, tables = _make_sb(
        proposed=_proposed("Brand New Topic"),
        topics=[{"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "published"}],
    )
    result = _run(
        monkeypatch,
        sb,
        decisions=[{"index": 0, "action": "add"}],
        retire_topic_ids=[],
    )
    assert result.added == 1 and result.replaced == 0 and result.retired == 0
    assert result.kept == 1  # the existing published topic, untouched
    topic_rows = tables["topics"].rows
    assert len(topic_rows) == 2
    new = next(r for r in topic_rows if r["id"] != T_PUB)
    assert new["name"] == "Brand New Topic"
    assert new["status"] == "draft"
    assert new["n"] == 2  # appended after n=1


# ═══ replace ══════════════════════════════════════════════════════════════
def test_resegment_replace_repoints_and_resets_the_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `replace` decision rewrites the existing topic's name, forces it
    back to `draft`, and clears `active_version_id` (the §4 progress reset
    re-arm) — the row itself is kept, not deleted."""
    sb, tables = _make_sb(
        proposed=_proposed("Revised Topic"),
        topics=[
            {
                "id": T_PUB,
                "unit_id": UNIT_ID,
                "n": 1,
                "name": "Old Topic",
                "status": "published",
                "active_version_id": VERSION_ID,
            }
        ],
    )
    result = _run(
        monkeypatch,
        sb,
        decisions=[{"index": 0, "action": "replace", "topic_id": T_PUB}],
        retire_topic_ids=[],
    )
    assert result.replaced == 1 and result.added == 0
    row = tables["topics"].rows[0]
    assert row["id"] == T_PUB  # same row — not deleted
    assert row["name"] == "Revised Topic"
    assert row["status"] == "draft"
    assert row["active_version_id"] is None


# ═══ retire ════════════════════════════════════════════════════════════════
def test_resegment_retire_marks_topic_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retired topic's `status` becomes `retired`; the row is not deleted."""
    sb, tables = _make_sb(
        proposed=_proposed("Something"),
        topics=[
            {"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "published"},
            {"id": T_DRAFT, "unit_id": UNIT_ID, "n": 2, "status": "draft"},
        ],
    )
    result = _run(
        monkeypatch,
        sb,
        decisions=[{"index": 0, "action": "add"}],
        retire_topic_ids=[T_DRAFT],
    )
    assert result.retired == 1
    retired = next(r for r in tables["topics"].rows if r["id"] == T_DRAFT)
    assert retired["status"] == "retired"


def test_resegment_keeps_untouched_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing topic neither replaced nor retired is left exactly as-is
    and counted as `kept`."""
    sb, tables = _make_sb(
        proposed=_proposed("New One"),
        topics=[
            {"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "published"},
        ],
    )
    result = _run(
        monkeypatch,
        sb,
        decisions=[{"index": 0, "action": "add"}],
        retire_topic_ids=[],
    )
    assert result.kept == 1
    kept = next(r for r in tables["topics"].rows if r["id"] == T_PUB)
    assert kept["status"] == "published"  # untouched


# ═══ validation — nothing mutates on a bad mapping ════════════════════════
def test_resegment_bad_index_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proposed index outside the breakdown raises `ConfirmError`."""
    sb, _t = _make_sb(
        proposed=_proposed("Only One"),
        topics=[{"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "draft"}],
    )
    with pytest.raises(ConfirmError) as exc:
        _run(
            monkeypatch,
            sb,
            decisions=[{"index": 5, "action": "add"}],
            retire_topic_ids=[],
        )
    assert exc.value.reason == "bad_index"


def test_resegment_unknown_topic_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `replace` / retire targeting a topic not in the unit raises."""
    sb, _t = _make_sb(
        proposed=_proposed("A Topic"),
        topics=[{"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "draft"}],
    )
    with pytest.raises(ConfirmError) as exc:
        _run(
            monkeypatch,
            sb,
            decisions=[
                {"index": 0, "action": "replace", "topic_id": OTHER_TOPIC}
            ],
            retire_topic_ids=[],
        )
    assert exc.value.reason == "bad_topic"


def test_resegment_replace_and_retire_conflict_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topic mapped to both replace and retire raises `ConfirmError`."""
    sb, _t = _make_sb(
        proposed=_proposed("A Topic"),
        topics=[{"id": T_PUB, "unit_id": UNIT_ID, "n": 1, "status": "published"}],
    )
    with pytest.raises(ConfirmError) as exc:
        _run(
            monkeypatch,
            sb,
            decisions=[{"index": 0, "action": "replace", "topic_id": T_PUB}],
            retire_topic_ids=[T_PUB],
        )
    assert exc.value.reason == "conflict"
