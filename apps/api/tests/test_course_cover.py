"""Tests for course cover-art generation (task 5.2).

`generate_course_cover` (`model-strategy.md` §4) is a best-effort, one-shot
background task: the first time a course is published it generates a cover
via Nano Banana 2, uploads it to the public `course-covers` bucket, and
records `courses.cover_image_path`. A course that already has a cover, or a
missing Supabase client, is a clean no-op.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.course_cover import generate_course_cover

COURSE_ID = "44444444-4444-4444-4444-444444444444"


class _CoursesTable:
    """A stateful `courses` table fake — select + update with `.eq()`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]
        self._mode = "select"
        self._f: dict[str, Any] = {}
        self._payload: dict[str, Any] = {}

    def select(self, *_a: Any) -> "_CoursesTable":
        self._mode, self._f = "select", {}
        return self

    def update(self, payload: dict[str, Any]) -> "_CoursesTable":
        self._mode, self._payload, self._f = "update", payload, {}
        return self

    def eq(self, key: str, value: Any) -> "_CoursesTable":
        self._f[key] = value
        return self

    def limit(self, _n: int) -> "_CoursesTable":
        return self

    def _match(self, r: dict[str, Any]) -> bool:
        return all(str(r.get(k)) == str(v) for k, v in self._f.items())

    def execute(self) -> MagicMock:
        if self._mode == "update":
            hit = [r for r in self.rows if self._match(r)]
            for r in hit:
                r.update(self._payload)
            return MagicMock(data=[dict(r) for r in hit])
        return MagicMock(data=[dict(r) for r in self.rows if self._match(r)])


def _make_sb(course: dict[str, Any]) -> tuple[MagicMock, _CoursesTable, MagicMock]:
    """Supabase mock; returns (client, `courses` fake, storage upload mock)."""
    courses = _CoursesTable([course])
    client = MagicMock(name="supabase")
    client.table.side_effect = (
        lambda name: courses if name == "courses" else MagicMock()
    )
    upload = client.storage.from_.return_value.upload
    return client, courses, upload


def _fake_gemini(image: bytes = b"PNGBYTES") -> MagicMock:
    g = MagicMock(name="gemini")
    g.generate_image = AsyncMock(return_value=image)
    return g


def test_generate_course_cover_creates_and_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A course with no cover gets an image generated, uploaded + recorded."""
    sb, courses, upload = _make_sb(
        {
            "id": COURSE_ID,
            "title": "Fluids",
            "subject": "Physics",
            "cover_image_path": None,
        }
    )
    gemini = _fake_gemini(b"PNGBYTES")
    monkeypatch.setattr("app.services.course_cover.get_supabase", lambda: sb)
    monkeypatch.setattr(
        "app.services.course_cover.GeminiService", lambda: gemini
    )

    asyncio.run(generate_course_cover(COURSE_ID))

    gemini.generate_image.assert_awaited_once()
    upload.assert_called_once()
    assert upload.call_args.args[0] == f"{COURSE_ID}.png"
    assert courses.rows[0]["cover_image_path"] == f"{COURSE_ID}.png"


def test_generate_course_cover_is_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A course that already has a `cover_image_path` is left untouched —
    re-publishing topics never regenerates the cover."""
    sb, courses, upload = _make_sb(
        {
            "id": COURSE_ID,
            "title": "Fluids",
            "subject": "Physics",
            "cover_image_path": "existing.png",
        }
    )
    gemini = _fake_gemini()
    monkeypatch.setattr("app.services.course_cover.get_supabase", lambda: sb)
    monkeypatch.setattr(
        "app.services.course_cover.GeminiService", lambda: gemini
    )

    asyncio.run(generate_course_cover(COURSE_ID))

    gemini.generate_image.assert_not_awaited()
    upload.assert_not_called()
    assert courses.rows[0]["cover_image_path"] == "existing.png"


def test_generate_course_cover_no_supabase_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Supabase client (local dev) — a clean no-op that never raises."""
    monkeypatch.setattr("app.services.course_cover.get_supabase", lambda: None)
    asyncio.run(generate_course_cover(COURSE_ID))  # must not raise
