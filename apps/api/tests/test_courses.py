"""Tests for the Supabase-backed courses endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_supabase_mock(rows: list[dict[str, Any]]) -> MagicMock:
    """Builds a supabase-py-shaped mock that returns ``rows`` on .execute()."""
    chain = MagicMock(name="builder")
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))

    client = MagicMock(name="supabase-client")
    client.table.return_value = chain
    client._chain = chain  # for assertions
    return client


# ─── /courses ─────────────────────────────────────────────────────────────
def test_list_courses_falls_back_to_sample_in_dev(client: Any) -> None:
    """Placeholder Supabase URL → returns deterministic sample courses."""
    r = client.get("/v1/courses")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert {"slug", "title", "id"}.issubset(body[0].keys())


def test_list_courses_uses_supabase_when_enabled(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a real client is available, courses come from Supabase."""
    fake_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "slug": "ap-physics-1",
            "title": "AP Physics 1 (from db)",
            "exam": "AP",
            "color_gradient": None,
            "icon_emoji": "⚛️",
            "sort_order": 1,
            "created_at": "2026-05-14T00:00:00+00:00",
        }
    ]
    sb = _build_supabase_mock(fake_rows)
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)

    r = client.get("/v1/courses")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "AP Physics 1 (from db)"

    # The query targeted the right table.
    sb.table.assert_called_with("courses")
    sb._chain.order.assert_called_with("sort_order")


def test_list_courses_falls_back_when_supabase_throws_in_dev(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supabase exception in dev mode → sample data, no 5xx."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("boom")
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)
    # supabase_enabled() returns False (dev placeholder), so we fall through.
    r = client.get("/v1/courses")
    assert r.status_code == 200


# ─── /topics/{id} ─────────────────────────────────────────────────────────
def test_get_topic_returns_derived_fallback_when_unknown(
    client: Any, dev_headers: dict[str, str]
) -> None:
    """Unknown topic returns a derived fallback (200) so the classroom page
    still renders rather than 404-ing mid-navigation. `id` is null and
    `has_content` is false — UI uses that to know it's a stub."""
    r = client.get(
        "/v1/topics/00000000-0000-0000-0000-000000000000", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] is None
    assert body["has_content"] is False


def test_get_topic_from_supabase(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "unit_id": "33333333-3333-3333-3333-333333333333",
        "n": 2,
        "name": "Wave Properties",
        "duration_min": 18,
        "summary": "Crests, troughs, λ, f, v=fλ.",
        "content": [{"tts": "Hi", "dur": 5}],
        "sort_order": 2,
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock([row])
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)

    r = client.get(
        "/v1/topics/22222222-2222-2222-2222-222222222222", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Wave Properties"
    # Filtered by the requested topic id.
    sb._chain.eq.assert_any_call("id", "22222222-2222-2222-2222-222222222222")


def test_get_topic_returns_derived_fallback_when_supabase_empty(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock([])
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)
    r = client.get(
        "/v1/topics/44444444-4444-4444-4444-444444444444", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] is None
    assert body["has_content"] is False


# ─── /courses/{slug}/units — retired-topic visibility (task 5.4) ──────────
# `dev_headers` authenticates as this id (see conftest.py).
_CALLER = "00000000-0000-0000-0000-000000000001"
_COURSE_ID = "c0000000-0000-0000-0000-0000000000c0"
_UNIT_ID = "c0000000-0000-0000-0000-0000000000u1"
_PUB_TOPIC = "c0000000-0000-0000-0000-00000000t001"
_RETIRED_TOPIC = "c0000000-0000-0000-0000-00000000t002"


class _UnitsQ:
    """A select builder applying `.eq()` + `.in_()` filters on execute."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._eq: dict[str, Any] = {}
        self._in: list[tuple[str, set[str]]] = []

    def select(self, *_a: Any) -> "_UnitsQ":
        return self

    def order(self, *_a: Any, **_k: Any) -> "_UnitsQ":
        return self

    def limit(self, *_a: Any) -> "_UnitsQ":
        return self

    def eq(self, key: str, value: Any) -> "_UnitsQ":
        self._eq[key] = value
        return self

    def in_(self, key: str, values: Any) -> "_UnitsQ":
        self._in.append((key, {str(v) for v in values}))
        return self

    def execute(self) -> MagicMock:
        out: list[dict[str, Any]] = []
        for r in self.rows:
            if not all(str(r.get(k)) == str(v) for k, v in self._eq.items()):
                continue
            if not all(str(r.get(k)) in vs for k, vs in self._in):
                continue
            out.append(dict(r))
        return MagicMock(data=out)


def _units_supabase(progress: list[dict[str, Any]]) -> MagicMock:
    """A Supabase mock for `list_course_units`: one course, one unit, a
    published + a retired topic, and the caller's `topic_progress` rows."""
    tables: dict[str, list[dict[str, Any]]] = {
        "courses": [{"id": _COURSE_ID, "slug": "fluids-x"}],
        "units": [{"id": _UNIT_ID, "n": 1, "name": "Unit 1", "course_id": _COURSE_ID}],
        "topics": [
            {"id": _PUB_TOPIC, "unit_id": _UNIT_ID, "n": 1, "name": "Pressure",
             "duration_min": 10, "status": "published"},
            {"id": _RETIRED_TOPIC, "unit_id": _UNIT_ID, "n": 2, "name": "Old Density",
             "duration_min": 9, "status": "retired"},
        ],
        "topic_progress": progress,
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: _UnitsQ(list(tables.get(name, [])))
    return client


def test_course_units_hides_retired_topic_from_new_student(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retired topic the caller never started is omitted from the tree."""
    sb = _units_supabase(progress=[])
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)

    r = client.get("/v1/courses/fluids-x/units", headers=dev_headers)
    assert r.status_code == 200
    topic_ids = {t["id"] for u in r.json() for t in u["topics"]}
    assert topic_ids == {_PUB_TOPIC}  # retired one hidden


def test_course_units_keeps_retired_topic_for_in_progress_student(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retired topic the caller has progress on is still shown to them."""
    sb = _units_supabase(
        progress=[{"topic_id": _RETIRED_TOPIC, "user_id": _CALLER}]
    )
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)

    r = client.get("/v1/courses/fluids-x/units", headers=dev_headers)
    assert r.status_code == 200
    topic_ids = {t["id"] for u in r.json() for t in u["topics"]}
    assert topic_ids == {_PUB_TOPIC, _RETIRED_TOPIC}  # in-progress keeps it
