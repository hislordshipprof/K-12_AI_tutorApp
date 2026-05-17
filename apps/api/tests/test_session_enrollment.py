"""Tests for lazy teacher-course enrollment on session start (task 4.3).

`teacher-authoring.md` §4: the first time a student opens a teacher
course the classroom's `POST /v1/sessions` call also inserts an
`enrollments` row, so the existing dashboard / progress / history
queries work unchanged. Recommended courses are left alone, and the
insert is idempotent.

Supabase is mocked: `.table(name)` dispatches to stateful `_Table`
fakes so the `enrollments` insert is observable.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# `dev_headers` authenticates as this id (see conftest.py).
CALLER = "00000000-0000-0000-0000-000000000001"
TOPIC = "11111111-1111-1111-1111-111111111111"
UNIT = "33333333-3333-3333-3333-333333333333"
COURSE = "44444444-4444-4444-4444-444444444444"

# A complete `lesson_sessions` row so the `SessionOut` response validates.
_SESSION_ROW = {
    "id": "99999999-9999-9999-9999-999999999999",
    "user_id": CALLER,
    "topic_id": TOPIC,
    "started_at": "2026-05-16T00:00:00+00:00",
    "ended_at": None,
    "agent_state": {},
    "created_at": "2026-05-16T00:00:00+00:00",
}


class _Table:
    """A stateful select / insert fake with `.eq()` filtering."""

    def __init__(
        self, rows: list[dict[str, Any]], insert_row: dict[str, Any] | None = None
    ) -> None:
        self.rows = [dict(r) for r in rows]
        # When set, an insert echoes this fixed row instead of the payload
        # (used by `lesson_sessions` to return a full session row).
        self.insert_row = insert_row
        self._mode = "select"
        self._f: dict[str, Any] = {}
        self._payload: dict[str, Any] = {}

    def select(self, *_a: Any) -> "_Table":
        self._mode, self._f = "select", {}
        return self

    def insert(self, payload: dict[str, Any]) -> "_Table":
        self._mode, self._payload = "insert", payload
        return self

    def eq(self, key: str, value: Any) -> "_Table":
        self._f[key] = value
        return self

    def limit(self, _n: int) -> "_Table":
        return self

    def _match(self, r: dict[str, Any]) -> bool:
        return all(str(r.get(k)) == str(v) for k, v in self._f.items())

    def execute(self) -> MagicMock:
        if self._mode == "insert":
            self.rows.append(dict(self._payload))
            return MagicMock(data=[dict(self.insert_row or self._payload)])
        return MagicMock(data=[dict(r) for r in self.rows if self._match(r)])


def _make_sb(
    *,
    origin: str = "teacher",
    enrollments: list[dict[str, Any]] | None = None,
) -> tuple[MagicMock, _Table]:
    """Build a Supabase mock; returns the client + the `enrollments` fake."""
    enr = _Table(enrollments or [])
    chains: dict[str, _Table] = {
        "lesson_sessions": _Table([], insert_row=_SESSION_ROW),
        "topics": _Table([{"id": TOPIC, "unit_id": UNIT}]),
        "units": _Table([{"id": UNIT, "course_id": COURSE}]),
        "courses": _Table([{"id": COURSE, "origin": origin}]),
        "enrollments": enr,
        "profiles": _Table([{"id": CALLER, "role": "student"}]),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: chains.get(name, _Table([]))
    return client, enr


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.sessions.get_supabase", lambda: sb)


def test_session_start_enrolls_in_teacher_course(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening a teacher-course topic inserts an `enrollments` row."""
    sb, enr = _make_sb(origin="teacher")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/sessions", headers=dev_headers, json={"topic_id": TOPIC}
    )
    assert r.status_code == 201
    assert len(enr.rows) == 1
    assert enr.rows[0]["user_id"] == CALLER
    assert enr.rows[0]["course_id"] == COURSE


def test_session_start_no_enroll_for_recommended_course(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Recommended course is left alone — it self-enrols elsewhere."""
    sb, enr = _make_sb(origin="recommended")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/sessions", headers=dev_headers, json={"topic_id": TOPIC}
    )
    assert r.status_code == 201
    assert enr.rows == []


def test_session_start_enrollment_is_idempotent(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-opening a teacher course does not create a duplicate enrollment."""
    sb, enr = _make_sb(
        origin="teacher",
        enrollments=[{"user_id": CALLER, "course_id": COURSE}],
    )
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/sessions", headers=dev_headers, json={"topic_id": TOPIC}
    )
    assert r.status_code == 201
    assert len(enr.rows) == 1  # no duplicate
