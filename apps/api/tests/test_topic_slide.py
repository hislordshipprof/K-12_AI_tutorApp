"""Tests for the classroom slide signed-URL endpoint (task 4.3).

`GET /v1/topics/{id}/slide/{topic_page_id}` mints a short-lived signed
URL for a teacher lesson's slide image (`teacher-authoring.md` §7 / §10).
It is gated: only the course owner, an admin, or an `active` member of a
class the course is assigned to may fetch it — everyone else, and any
missing row, gets 404 so a non-member learns nothing about the slide.

Supabase is mocked: `.table(name)` yields a fresh `_Q` builder and
`.storage.from_(...).create_signed_url(...)` returns a canned dict.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# `dev_headers` authenticates as this id (see conftest.py).
CALLER = "00000000-0000-0000-0000-000000000001"
OWNER = "00000000-0000-0000-0000-0000000000aa"
TOPIC = "11111111-1111-1111-1111-111111111111"
OTHER_TOPIC = "11111111-1111-1111-1111-1111111111ff"
TOPIC_PAGE = "22222222-2222-2222-2222-222222222222"
UNIT = "33333333-3333-3333-3333-333333333333"
COURSE = "44444444-4444-4444-4444-444444444444"
CLASS = "55555555-5555-5555-5555-555555555555"
MATERIAL = "66666666-6666-6666-6666-666666666666"
SIGNED = "https://signed.example/lesson-materials/slide.png?token=abc"


class _Q:
    """A select builder applying `.eq()` / `.in_()` filters on execute."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._eq: dict[str, Any] = {}
        self._in: list[tuple[str, set[str]]] = []

    def select(self, *_a: Any) -> "_Q":
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
    role: str = "student",
    owner_id: str = OWNER,
    topic_page_topic: str = TOPIC,
    class_courses: list[dict[str, Any]] | None = None,
    class_members: list[dict[str, Any]] | None = None,
    image_path: str | None = "owner/mat/pages/5.png",
) -> MagicMock:
    """Build a Supabase mock for the slide endpoint's table + storage calls."""
    tables: dict[str, list[dict[str, Any]]] = {
        "topic_pages": [
            {
                "id": TOPIC_PAGE,
                "topic_id": topic_page_topic,
                "material_id": MATERIAL,
                "page_idx": 5,
            }
        ],
        "topics": [{"id": TOPIC, "unit_id": UNIT}],
        "units": [{"id": UNIT, "course_id": COURSE}],
        "courses": [{"id": COURSE, "owner_id": owner_id}],
        "profiles": [{"id": CALLER, "role": role}],
        "class_courses": class_courses or [],
        "class_members": class_members or [],
        "material_pages": (
            [{"material_id": MATERIAL, "idx": 5, "image_path": image_path}]
            if image_path
            else []
        ),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: _Q(list(tables.get(name, [])))
    client.storage.from_.return_value.create_signed_url.return_value = {
        "signedURL": SIGNED
    }
    return client


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.courses.get_supabase", lambda: sb)


def test_slide_signed_url_for_active_member(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active member of a class the course is assigned to gets a URL."""
    sb = _make_sb(
        class_courses=[{"class_id": CLASS, "course_id": COURSE}],
        class_members=[
            {"class_id": CLASS, "student_id": CALLER, "status": "active"}
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/topics/{TOPIC}/slide/{TOPIC_PAGE}", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == {"url": SIGNED}


def test_slide_signed_url_for_course_owner(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The course owner (a teacher previewing) gets a URL — no membership."""
    sb = _make_sb(owner_id=CALLER)
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/topics/{TOPIC}/slide/{TOPIC_PAGE}", headers=dev_headers)
    assert r.status_code == 200
    assert r.json()["url"] == SIGNED


def test_slide_signed_url_for_admin(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin caller gets a URL without owning the course or membership."""
    sb = _make_sb(role="admin")
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/topics/{TOPIC}/slide/{TOPIC_PAGE}", headers=dev_headers)
    assert r.status_code == 200


def test_slide_non_member_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller who is neither owner, admin, nor an active member 404s — a
    `pending` membership is not enough."""
    sb = _make_sb(
        class_courses=[{"class_id": CLASS, "course_id": COURSE}],
        class_members=[
            {"class_id": CLASS, "student_id": CALLER, "status": "pending"}
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/topics/{TOPIC}/slide/{TOPIC_PAGE}", headers=dev_headers)
    assert r.status_code == 404


def test_slide_topic_page_mismatch_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `topic_page` row that belongs to a different topic 404s, even for
    the course owner — the page must be claimed by the requested topic."""
    sb = _make_sb(owner_id=CALLER, topic_page_topic=OTHER_TOPIC)
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/topics/{TOPIC}/slide/{TOPIC_PAGE}", headers=dev_headers)
    assert r.status_code == 404
