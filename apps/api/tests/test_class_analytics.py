"""Tests for per-class analytics (task 5.3).

`GET /v1/teacher/classes/{id}/analytics` reports, for every PUBLISHED topic
of every course assigned to a class, how many of the class's **active**
students started it, how many completed it, and their average score —
grouped course -> unit -> topic. Teacher/admin-gated; the class must be the
caller's own.

Supabase is mocked: `.table(name)` yields a fresh `_Q` select builder that
applies `.eq()` / `.in_()` filters on execute, so the endpoint's real
scoping (active members, assigned courses, published topics) is exercised.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# `dev_headers` authenticates as this id (see conftest.py).
TEACHER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-0000000000ff"
CLASS_ID = "11111111-1111-1111-1111-111111111111"
COURSE_ID = "22222222-2222-2222-2222-222222222222"
UNIT_ID = "33333333-3333-3333-3333-333333333333"
TOPIC1 = "44444444-4444-4444-4444-444444444441"
TOPIC2 = "44444444-4444-4444-4444-444444444442"
TOPIC_DRAFT = "44444444-4444-4444-4444-44444444443d"
STUDENT_A = "55555555-5555-5555-5555-55555555550a"
STUDENT_B = "55555555-5555-5555-5555-55555555550b"


class _Q:
    """A select builder applying `.eq()` + `.in_()` filters on execute."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._eq: dict[str, Any] = {}
        self._in: list[tuple[str, set[str]]] = []

    def select(self, *_a: Any) -> "_Q":
        return self

    def order(self, *_a: Any) -> "_Q":
        return self

    def limit(self, *_a: Any) -> "_Q":
        return self

    def eq(self, key: str, value: Any) -> "_Q":
        self._eq[key] = value
        return self

    def in_(self, key: str, values: Any) -> "_Q":
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


def _make_sb(
    *,
    role: str = "teacher",
    class_teacher: str = TEACHER,
    members: list[dict[str, Any]] | None = None,
    class_courses: list[dict[str, Any]] | None = None,
    topics: list[dict[str, Any]] | None = None,
    topic_progress: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock whose `.table(name)` yields a fresh `_Q`."""
    tables: dict[str, list[dict[str, Any]]] = {
        "profiles": [{"id": TEACHER, "role": role}],
        "classes": [
            {
                "id": CLASS_ID,
                "name": "Period 1",
                "subject": "Physics",
                "join_code": "PHYS-AAAA",
                "teacher_id": class_teacher,
                "archived": False,
            }
        ],
        "class_members": members
        if members is not None
        else [
            {"class_id": CLASS_ID, "student_id": STUDENT_A, "status": "active"},
            {"class_id": CLASS_ID, "student_id": STUDENT_B, "status": "active"},
        ],
        "class_courses": class_courses
        if class_courses is not None
        else [{"class_id": CLASS_ID, "course_id": COURSE_ID}],
        "courses": [{"id": COURSE_ID, "title": "Fluids"}],
        "units": [
            {"id": UNIT_ID, "course_id": COURSE_ID, "name": "Unit 1", "n": 1}
        ],
        "topics": topics
        if topics is not None
        else [
            {"id": TOPIC1, "unit_id": UNIT_ID, "name": "Pressure", "n": 1,
             "status": "published"},
            {"id": TOPIC2, "unit_id": UNIT_ID, "name": "Buoyancy", "n": 2,
             "status": "published"},
            {"id": TOPIC_DRAFT, "unit_id": UNIT_ID, "name": "Draft", "n": 3,
             "status": "draft"},
        ],
        "topic_progress": topic_progress or [],
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: _Q(list(tables.get(name, [])))
    return client


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)


def test_analytics_aggregates_progress_per_topic(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per published topic: started = students with a progress row,
    completed = status 'done', avg_score = mean of non-null scores."""
    sb = _make_sb(
        members=[
            {"class_id": CLASS_ID, "student_id": STUDENT_A, "status": "active"},
            {"class_id": CLASS_ID, "student_id": STUDENT_B, "status": "active"},
            # a pending member must NOT count toward the aggregates.
            {"class_id": CLASS_ID, "student_id": OTHER, "status": "pending"},
        ],
        topic_progress=[
            {"topic_id": TOPIC1, "user_id": STUDENT_A, "status": "done",
             "score": 80},
            {"topic_id": TOPIC1, "user_id": STUDENT_B, "status": "in_progress",
             "score": None},
            {"topic_id": TOPIC2, "user_id": STUDENT_A, "status": "done",
             "score": 60},
            # progress by a non-member must be ignored.
            {"topic_id": TOPIC1, "user_id": OTHER, "status": "done",
             "score": 100},
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(
        f"/v1/teacher/classes/{CLASS_ID}/analytics", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["student_count"] == 2  # actives only

    topics = body["courses"][0]["units"][0]["topics"]
    by_id = {t["topic_id"]: t for t in topics}
    # Draft topic excluded entirely.
    assert TOPIC_DRAFT not in by_id
    assert set(by_id) == {TOPIC1, TOPIC2}

    t1 = by_id[TOPIC1]
    assert t1["started"] == 2 and t1["completed"] == 1
    assert t1["avg_score"] == 80  # only A had a score; OTHER ignored

    t2 = by_id[TOPIC2]
    assert t2["started"] == 1 and t2["completed"] == 1
    assert t2["avg_score"] == 60


def test_analytics_empty_class_reports_zeroes(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A class with no students still lists its published topics — every
    topic at 0 started / 0 completed / no score."""
    sb = _make_sb(members=[])
    _wire(monkeypatch, sb)

    r = client.get(
        f"/v1/teacher/classes/{CLASS_ID}/analytics", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["student_count"] == 0
    topics = body["courses"][0]["units"][0]["topics"]
    assert len(topics) == 2
    for t in topics:
        assert t["started"] == 0
        assert t["completed"] == 0
        assert t["avg_score"] is None


def test_analytics_omits_courses_with_no_published_topics(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A course whose every topic is still draft is dropped from the view."""
    sb = _make_sb(
        topics=[
            {"id": TOPIC_DRAFT, "unit_id": UNIT_ID, "name": "Draft", "n": 1,
             "status": "draft"},
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(
        f"/v1/teacher/classes/{CLASS_ID}/analytics", headers=dev_headers
    )
    assert r.status_code == 200
    assert r.json()["courses"] == []


def test_analytics_non_owned_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A class owned by another teacher 404s."""
    sb = _make_sb(class_teacher=OTHER)
    _wire(monkeypatch, sb)

    r = client.get(
        f"/v1/teacher/classes/{CLASS_ID}/analytics", headers=dev_headers
    )
    assert r.status_code == 404


def test_analytics_non_teacher_is_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot read class analytics."""
    sb = _make_sb(role="student")
    _wire(monkeypatch, sb)

    r = client.get(
        f"/v1/teacher/classes/{CLASS_ID}/analytics", headers=dev_headers
    )
    assert r.status_code == 403
