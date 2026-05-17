"""Tests for the split dashboard course list (task 4.1).

`GET /v1/me/courses` returns the student's courses tagged with a `group`
field — `'recommended'` (built-in `origin='recommended'` courses) and
`'teacher'` (courses assigned to a class the caller actively belongs to,
each with a `published_topic_count`). `GET /v1/courses` (the public
landing-page picker) is scoped to Recommended courses only.

Supabase is mocked: `.table(name)` dispatches to a fresh `_Q` builder that
applies `.eq()` / `.in_()` filters on execute, so the endpoint's real
scoping (active membership, published topics, `origin`) is exercised.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# `dev_headers` authenticates as this id (see conftest.py).
CALLER = "00000000-0000-0000-0000-000000000001"
CLASS_ID = "11111111-1111-1111-1111-111111111111"
REC_COURSE = "22222222-2222-2222-2222-222222222222"
TEACHER_COURSE = "33333333-3333-3333-3333-333333333333"
UNIT_ID = "44444444-4444-4444-4444-444444444444"


class _Q:
    """A select builder that applies `.eq()` + `.in_()` filters on execute."""

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


def _make_supabase(**tables: list[dict[str, Any]]) -> MagicMock:
    """A Supabase mock whose `.table(name)` yields a FRESH `_Q` each call."""
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: _Q(list(tables.get(name, [])))
    return client


def _course(cid: str, slug: str, origin: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "exam": extra.get("exam"),
        "subject": extra.get("subject"),
        "color_gradient": None,
        "icon_emoji": None,
        "origin": origin,
        "sort_order": extra.get("sort_order", 0),
        "created_at": "2026-05-14T00:00:00+00:00",
    }


# ═══ GET /v1/me/courses ═══════════════════════════════════════════════════
def test_my_courses_returns_recommended_only_without_memberships(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A student with no active class membership sees only Recommended."""
    sb = _make_supabase(
        courses=[_course(REC_COURSE, "ap-physics-1", "recommended", exam="AP")],
        class_members=[],
    )
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.get("/v1/me/courses", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["group"] == "recommended"
    assert body[0]["slug"] == "ap-physics-1"
    assert body[0]["published_topic_count"] is None


def test_my_courses_includes_teacher_course_for_active_member(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active member sees the class's teacher course under group='teacher'
    with a published-topic count."""
    sb = _make_supabase(
        courses=[
            _course(REC_COURSE, "ap-physics-1", "recommended", exam="AP"),
            _course(TEACHER_COURSE, "fluids-x", "teacher", subject="Physics"),
        ],
        class_members=[
            {"class_id": CLASS_ID, "student_id": CALLER, "status": "active"}
        ],
        class_courses=[{"class_id": CLASS_ID, "course_id": TEACHER_COURSE}],
        units=[{"id": UNIT_ID, "course_id": TEACHER_COURSE}],
        topics=[
            {"unit_id": UNIT_ID, "status": "published"},
            {"unit_id": UNIT_ID, "status": "published"},
            {"unit_id": UNIT_ID, "status": "draft"},
        ],
    )
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.get("/v1/me/courses", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    by_group = {c["group"]: c for c in body}
    assert by_group["recommended"]["slug"] == "ap-physics-1"
    teacher = by_group["teacher"]
    assert teacher["id"] == TEACHER_COURSE
    # 2 published, 1 draft → count is 2.
    assert teacher["published_topic_count"] == 2


def test_my_courses_teacher_course_with_no_published_topics(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An all-draft teacher course is returned with published_topic_count 0
    (the dashboard renders it 'coming soon')."""
    sb = _make_supabase(
        courses=[_course(TEACHER_COURSE, "fluids-x", "teacher", subject="Physics")],
        class_members=[
            {"class_id": CLASS_ID, "student_id": CALLER, "status": "active"}
        ],
        class_courses=[{"class_id": CLASS_ID, "course_id": TEACHER_COURSE}],
        units=[{"id": UNIT_ID, "course_id": TEACHER_COURSE}],
        topics=[{"unit_id": UNIT_ID, "status": "draft"}],
    )
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.get("/v1/me/courses", headers=dev_headers)
    assert r.status_code == 200
    teacher = next(c for c in r.json() if c["group"] == "teacher")
    assert teacher["published_topic_count"] == 0


def test_my_courses_surfaces_pending_membership_as_awaiting_approval(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending (not yet approved) membership grants no teacher course but
    is surfaced as a `group='pending'` item — id = class id, title = class
    name — so the dashboard can show "awaiting approval" (task 4.2)."""
    sb = _make_supabase(
        courses=[
            _course(REC_COURSE, "ap-physics-1", "recommended", exam="AP"),
            _course(TEACHER_COURSE, "fluids-x", "teacher", subject="Physics"),
        ],
        classes=[{"id": CLASS_ID, "name": "Period 1 Physics"}],
        class_members=[
            {"class_id": CLASS_ID, "student_id": CALLER, "status": "pending"}
        ],
        class_courses=[{"class_id": CLASS_ID, "course_id": TEACHER_COURSE}],
    )
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.get("/v1/me/courses", headers=dev_headers)
    assert r.status_code == 200
    by_group: dict[str, list[dict[str, Any]]] = {}
    for c in r.json():
        by_group.setdefault(c["group"], []).append(c)
    # The unapproved membership leaks no teacher course…
    assert "teacher" not in by_group
    # …but the class itself shows up as awaiting approval.
    pending = by_group["pending"]
    assert len(pending) == 1
    assert pending[0]["id"] == CLASS_ID
    assert pending[0]["title"] == "Period 1 Physics"
    assert pending[0]["slug"] is None
    assert pending[0]["published_topic_count"] is None


def test_my_courses_pending_and_active_memberships_coexist(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller with one active and one pending membership sees the active
    class's teacher course AND the pending class as awaiting approval."""
    other_class = "55555555-5555-5555-5555-555555555555"
    sb = _make_supabase(
        courses=[
            _course(REC_COURSE, "ap-physics-1", "recommended", exam="AP"),
            _course(TEACHER_COURSE, "fluids-x", "teacher", subject="Physics"),
        ],
        classes=[{"id": other_class, "name": "Period 2 Chemistry"}],
        class_members=[
            {"class_id": CLASS_ID, "student_id": CALLER, "status": "active"},
            {"class_id": other_class, "student_id": CALLER, "status": "pending"},
        ],
        class_courses=[{"class_id": CLASS_ID, "course_id": TEACHER_COURSE}],
        units=[{"id": UNIT_ID, "course_id": TEACHER_COURSE}],
        topics=[{"unit_id": UNIT_ID, "status": "published"}],
    )
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.get("/v1/me/courses", headers=dev_headers)
    assert r.status_code == 200
    by_group: dict[str, list[dict[str, Any]]] = {}
    for c in r.json():
        by_group.setdefault(c["group"], []).append(c)
    assert by_group["teacher"][0]["id"] == TEACHER_COURSE
    assert by_group["pending"][0]["title"] == "Period 2 Chemistry"


# ═══ GET /v1/courses — scoped to Recommended ══════════════════════════════
def test_list_courses_excludes_teacher_courses(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public picker returns only `origin='recommended'` courses — a
    teacher course in the table never leaks onto the landing page."""
    sb = _make_supabase(
        courses=[
            _course(REC_COURSE, "ap-physics-1", "recommended", exam="AP"),
            _course(TEACHER_COURSE, "fluids-x", "teacher", subject="Physics"),
        ],
    )
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)

    r = client.get("/v1/courses")
    assert r.status_code == 200
    slugs = {c["slug"] for c in r.json()}
    assert slugs == {"ap-physics-1"}
