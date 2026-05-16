"""Tests for the teacher home-page list endpoints (task 3.1).

Covers `GET /v1/teacher/classes` and `GET /v1/teacher/courses` — the two
endpoints that power the teacher home page (`/teach`):

  1. `/classes` returns the caller's non-archived classes with correct
     `student_count` / `pending_count` aggregates;
  2. a teacher with no classes gets `[]` (HTTP 200, not an error);
  3. `/courses` returns the caller's courses with correct
     `unit_count` / `topic_count` / `published_count` / `draft_count`;
  4. a teacher with no courses gets `[]`;
  5. a `student`-role caller is 403'd by the `require_role` gate.

Supabase is mocked: a MagicMock client whose `.table(name)` dispatches to
a per-table select chain, mirroring `test_pipeline_jobs.py`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# `dev_headers` authenticates as this id (see conftest.py).
TEACHER_ID = "00000000-0000-0000-0000-000000000001"


def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A MagicMock that mimics a Supabase select builder chain."""
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "in_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


def _profiles_role(role: str) -> MagicMock:
    return _select_chain([{"role": role}])


def _make_supabase(tables: dict[str, list[dict[str, Any]]], role: str) -> MagicMock:
    """Supabase mock dispatching each table name to its rows."""
    chains = {name: _select_chain(rows) for name, rows in tables.items()}
    chains["profiles"] = _profiles_role(role)
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: chains.get(name, _select_chain([]))
    return client


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    """Point both the security and teacher modules at the mock client."""
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)


# ═══ GET /v1/teacher/classes ══════════════════════════════════════════════
def test_list_classes_returns_scoped_classes_with_counts(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller's non-archived classes come back with active/pending counts;
    an archived class is excluded."""
    classes = [
        {
            "id": "c1",
            "name": "Period 1 Physics",
            "join_code": "ABC123",
            "subject": "Physics",
            "archived": False,
        },
        {
            "id": "c2",
            "name": "Period 2 Math",
            "join_code": "XYZ789",
            "subject": None,
            "archived": False,
        },
        {
            "id": "c3",
            "name": "Old Class",
            "join_code": "OLD000",
            "subject": "Bio",
            "archived": True,
        },
    ]
    members = [
        {"class_id": "c1", "status": "active"},
        {"class_id": "c1", "status": "active"},
        {"class_id": "c1", "status": "pending"},
        {"class_id": "c2", "status": "pending"},
    ]
    sb = _make_supabase(
        {"classes": classes, "class_members": members}, role="teacher"
    )
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/classes", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    # Archived class c3 is excluded.
    assert [c["id"] for c in body] == ["c1", "c2"]

    c1 = next(c for c in body if c["id"] == "c1")
    assert c1["name"] == "Period 1 Physics"
    assert c1["join_code"] == "ABC123"
    assert c1["subject"] == "Physics"
    assert c1["student_count"] == 2
    assert c1["pending_count"] == 1

    c2 = next(c for c in body if c["id"] == "c2")
    assert c2["subject"] is None
    assert c2["student_count"] == 0
    assert c2["pending_count"] == 1


def test_list_classes_empty_for_teacher_with_no_classes(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher with no classes gets an empty array, not an error."""
    sb = _make_supabase({"classes": [], "class_members": []}, role="teacher")
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/classes", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_classes_non_teacher_gets_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller is forbidden from the classes endpoint."""
    sb = _make_supabase({"classes": [], "class_members": []}, role="student")
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/classes", headers=dev_headers)
    assert r.status_code == 403


# ═══ GET /v1/teacher/courses ══════════════════════════════════════════════
def test_list_courses_returns_scoped_courses_with_counts(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller's courses come back with unit/topic aggregate counts,
    split by topic status."""
    courses = [
        {
            "id": "co1",
            "title": "My Physics Course",
            "subject": "Physics",
            "grade_band": "9-12",
            "icon_emoji": "⚛️",
            "color_gradient": "from-sky-400 to-indigo-500",
        },
        {
            "id": "co2",
            "title": "Empty Course",
            "subject": None,
            "grade_band": None,
            "icon_emoji": None,
            "color_gradient": None,
        },
    ]
    units = [
        {"id": "u1", "course_id": "co1"},
        {"id": "u2", "course_id": "co1"},
        # co2 has no units.
    ]
    topics = [
        {"id": "t1", "unit_id": "u1", "status": "published"},
        {"id": "t2", "unit_id": "u1", "status": "draft"},
        {"id": "t3", "unit_id": "u2", "status": "published"},
        {"id": "t4", "unit_id": "u2", "status": "draft"},
        {"id": "t5", "unit_id": "u2", "status": "draft"},
    ]
    sb = _make_supabase(
        {"courses": courses, "units": units, "topics": topics}, role="teacher"
    )
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/courses", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert [c["id"] for c in body] == ["co1", "co2"]

    co1 = next(c for c in body if c["id"] == "co1")
    assert co1["title"] == "My Physics Course"
    assert co1["subject"] == "Physics"
    assert co1["grade_band"] == "9-12"
    assert co1["icon_emoji"] == "⚛️"
    assert co1["color_gradient"] == "from-sky-400 to-indigo-500"
    assert co1["unit_count"] == 2
    assert co1["topic_count"] == 5
    assert co1["published_count"] == 2
    assert co1["draft_count"] == 3

    co2 = next(c for c in body if c["id"] == "co2")
    assert co2["subject"] is None
    assert co2["grade_band"] is None
    assert co2["unit_count"] == 0
    assert co2["topic_count"] == 0
    assert co2["published_count"] == 0
    assert co2["draft_count"] == 0


def test_list_courses_empty_for_teacher_with_no_courses(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher with no courses gets an empty array, not an error."""
    sb = _make_supabase(
        {"courses": [], "units": [], "topics": []}, role="teacher"
    )
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/courses", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_courses_non_teacher_gets_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller is forbidden from the courses endpoint."""
    sb = _make_supabase(
        {"courses": [], "units": [], "topics": []}, role="student"
    )
    _wire(monkeypatch, sb)

    r = client.get("/v1/teacher/courses", headers=dev_headers)
    assert r.status_code == 403
