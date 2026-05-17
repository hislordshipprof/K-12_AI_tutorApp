"""Tests for class↔course assignment (task 3.6).

`POST /v1/teacher/classes/{id}/courses` assigns one of the teacher's
courses to one of their classes — the `class_courses` link that makes a
teacher course visible to the class's students. `DELETE` unassigns it.
Both endpoints are teacher/admin-gated and require the caller to own BOTH
the class and (for assign) the course.

Supabase is mocked: `.table(name)` dispatches to stateful `_Table` fakes
so an insert/delete is observable, mirroring `test_class_management.py`.
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


class _Table:
    """A stateful select / insert / delete fake with `.eq()` filtering."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._mode = "select"
        self._f: dict[str, Any] = {}
        self._payload: dict[str, Any] = {}

    def select(self, *_a: Any) -> "_Table":
        self._mode, self._f = "select", {}
        return self

    def insert(self, payload: dict[str, Any]) -> "_Table":
        self._mode, self._payload = "insert", payload
        return self

    def delete(self) -> "_Table":
        self._mode, self._f = "delete", {}
        return self

    def eq(self, key: str, value: Any) -> "_Table":
        self._f[key] = value
        return self

    def limit(self, _n: int) -> "_Table":
        return self

    def _match(self, r: dict[str, Any]) -> bool:
        return all(str(r.get(k)) == str(v) for k, v in self._f.items())

    def execute(self) -> MagicMock:
        if self._mode == "select":
            return MagicMock(data=[dict(r) for r in self.rows if self._match(r)])
        if self._mode == "insert":
            self.rows.append(dict(self._payload))
            return MagicMock(data=[dict(self._payload)])
        if self._mode == "delete":
            hit = [r for r in self.rows if self._match(r)]
            self.rows = [r for r in self.rows if not self._match(r)]
            return MagicMock(data=hit)
        return MagicMock(data=[])


def _make_sb(
    *,
    role: str = "teacher",
    class_teacher: str = TEACHER,
    course_owner: str = TEACHER,
    class_courses: list[dict[str, Any]] | None = None,
) -> tuple[MagicMock, _Table]:
    """Build a Supabase mock; returns the client + the `class_courses` fake."""
    cc = _Table(class_courses or [])
    chains: dict[str, _Table] = {
        "profiles": _Table([{"id": TEACHER, "role": role}]),
        "classes": _Table(
            [
                {
                    "id": CLASS_ID,
                    "name": "Period 1",
                    "subject": "Physics",
                    "join_code": "PHYS-AAAA",
                    "teacher_id": class_teacher,
                    "archived": False,
                }
            ]
        ),
        "courses": _Table(
            [
                {
                    "id": COURSE_ID,
                    "title": "Fluids",
                    "subject": "Physics",
                    "grade_band": "9-12",
                    "teaching_style": None,
                    "owner_id": course_owner,
                }
            ]
        ),
        "class_courses": cc,
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: chains.get(name, _Table([]))
    return client, cc


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)


# ═══ POST /v1/teacher/classes/{id}/courses ════════════════════════════════
def test_assign_course_creates_class_courses_row(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assigning a course inserts a `class_courses` row and echoes the course."""
    sb, cc = _make_sb()
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/courses",
        headers=dev_headers,
        json={"course_id": COURSE_ID},
    )
    assert r.status_code == 201
    assert r.json() == {"id": COURSE_ID, "title": "Fluids"}
    assert len(cc.rows) == 1
    assert cc.rows[0]["class_id"] == CLASS_ID
    assert cc.rows[0]["course_id"] == COURSE_ID


def test_assign_course_is_idempotent(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-assigning an already-assigned course does not create a duplicate."""
    sb, cc = _make_sb(
        class_courses=[{"class_id": CLASS_ID, "course_id": COURSE_ID}]
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/courses",
        headers=dev_headers,
        json={"course_id": COURSE_ID},
    )
    assert r.status_code == 201
    assert len(cc.rows) == 1  # no duplicate


def test_assign_course_non_owned_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assigning to a class owned by another teacher 404s."""
    sb, _cc = _make_sb(class_teacher=OTHER)
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/courses",
        headers=dev_headers,
        json={"course_id": COURSE_ID},
    )
    assert r.status_code == 404


def test_assign_non_owned_course_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher cannot assign a course they do not own."""
    sb, _cc = _make_sb(course_owner=OTHER)
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/courses",
        headers=dev_headers,
        json={"course_id": COURSE_ID},
    )
    assert r.status_code == 404


def test_assign_course_non_teacher_is_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot assign courses."""
    sb, _cc = _make_sb(role="student")
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/courses",
        headers=dev_headers,
        json={"course_id": COURSE_ID},
    )
    assert r.status_code == 403


# ═══ DELETE /v1/teacher/classes/{id}/courses/{course_id} ══════════════════
def test_unassign_course_deletes_row_204(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unassigning deletes the `class_courses` row and returns 204."""
    sb, cc = _make_sb(
        class_courses=[{"class_id": CLASS_ID, "course_id": COURSE_ID}]
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/classes/{CLASS_ID}/courses/{COURSE_ID}",
        headers=dev_headers,
    )
    assert r.status_code == 204
    assert cc.rows == []


def test_unassign_course_non_owned_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unassigning from a class owned by another teacher 404s and deletes
    nothing."""
    sb, cc = _make_sb(
        class_teacher=OTHER,
        class_courses=[{"class_id": CLASS_ID, "course_id": COURSE_ID}],
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/classes/{CLASS_ID}/courses/{COURSE_ID}",
        headers=dev_headers,
    )
    assert r.status_code == 404
    assert len(cc.rows) == 1  # untouched
