"""Tests for the course/unit authoring endpoints (task 3.3).

Covers the teacher course-authoring screen backend (`teacher-authoring.md`
§4/§6/§9):

  * `POST /v1/teacher/courses` — create a teacher-authored course with a
    generated unique slug; a non-teacher is 403'd; an empty title 422s.
  * `GET /v1/teacher/courses/{id}` — units with per-unit material counts +
    `teaching_style`; a course owned by a different teacher 404s.
  * `PATCH /v1/teacher/courses/{id}` — sets `teaching_style`; a non-owned
    course 404s.
  * `POST /v1/teacher/courses/{id}/units` — creates a unit with the next
    `n`; a non-owned course 404s.
  * `GET /v1/teacher/units/{id}` — materials with `status` from
    `conversion_status`; a non-owned unit 404s.
  * `POST /v1/teacher/units/{id}/materials` — multipart upload; pre-validates
    every file then ingests; a spoofed file 400s before any ingest; a
    non-owned unit 404s.

Supabase is mocked: a MagicMock client whose `.table(name)` dispatches to a
per-table builder, mirroring `test_class_management.py`. A small stateful
table fake is used where an endpoint reads back what it just wrote.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipeline.ingest import IngestResult

# `dev_headers` authenticates as this id (see conftest.py).
TEACHER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TEACHER_ID = "00000000-0000-0000-0000-0000000000ff"
COURSE_ID = "11111111-1111-1111-1111-111111111111"
UNIT_ID = "22222222-2222-2222-2222-222222222222"
UNIT_2_ID = "33333333-3333-3333-3333-333333333333"
MATERIAL_ID = "44444444-4444-4444-4444-444444444444"


# ─── select-chain mock (read-only tables) ─────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A MagicMock that mimics a Supabase select builder chain."""
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "in_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


# ─── stateful generic table fake ──────────────────────────────────────────
class _Table:
    """A minimal stand-in for a Supabase table.

    Models the select / insert / update chains the endpoints use against an
    in-memory list, with `.eq()` filters applied on execute, so a read after
    a write reflects the change (like Postgres). An optional `id_for` hook
    assigns ids to inserted rows that omit one.
    """

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        id_for: Any = None,
    ) -> None:
        self.rows = [dict(r) for r in rows]
        self._id_for = id_for

    def select(self, _columns: str = "*") -> "_Table":
        self._mode = "select"
        self._filters: dict[str, Any] = {}
        return self

    def insert(self, payload: dict[str, Any]) -> "_Table":
        self._mode = "insert"
        self._payload = dict(payload)
        return self

    def update(self, payload: dict[str, Any]) -> "_Table":
        self._mode = "update"
        self._payload = dict(payload)
        self._filters = {}
        return self

    def eq(self, key: str, value: Any) -> "_Table":
        self._filters[key] = value
        return self

    def in_(self, key: str, values: Any) -> "_Table":
        self._in = (key, [str(v) for v in values])
        return self

    def limit(self, _n: int) -> "_Table":
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Table":
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        ok = all(str(row.get(k)) == str(v) for k, v in self._filters.items())
        if ok and getattr(self, "_in", None) is not None:
            key, values = self._in
            ok = str(row.get(key)) in values
        return ok

    def execute(self) -> MagicMock:
        if self._mode == "select":
            return MagicMock(data=[r for r in self.rows if self._matches(r)])
        if self._mode == "insert":
            row = dict(self._payload)
            if "id" not in row:
                row["id"] = self._id_for() if self._id_for else "generated-id"
            self.rows.append(row)
            return MagicMock(data=[dict(row)])
        if self._mode == "update":
            hit = [r for r in self.rows if self._matches(r)]
            for r in hit:
                r.update(self._payload)
            return MagicMock(data=[dict(r) for r in hit])
        return MagicMock(data=[])


def _make_supabase(
    *,
    role: str,
    courses: _Table | list[dict[str, Any]] | None = None,
    units: _Table | list[dict[str, Any]] | None = None,
    materials: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock dispatching each table name to its builder.

    `profiles` answers the `.select("role")` role lookup that
    `get_user_role` performs.
    """
    courses_tbl = courses if isinstance(courses, _Table) else _Table(courses or [])
    units_tbl = units if isinstance(units, _Table) else _Table(units or [])

    chains: dict[str, Any] = {
        "courses": courses_tbl,
        "units": units_tbl,
        "lesson_materials": _Table(materials or []),
        "profiles": _select_chain([{"role": role}]),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: chains.get(name, _select_chain([]))
    return client


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    """Point the security + teacher router at the mock client."""
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)


# ═══ POST /v1/teacher/courses ═════════════════════════════════════════════
def test_create_course_returns_course_shape(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a course returns the list-item shape with zero counts; the
    inserted row carries origin='teacher', owner_id=caller, a non-empty
    slug."""
    courses = _Table([], id_for=lambda: COURSE_ID)
    sb = _make_supabase(role="teacher", courses=courses)
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/courses",
        headers=dev_headers,
        json={"title": "Intro to Physics!", "subject": "Physics", "grade_band": "9-12"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == COURSE_ID
    assert body["title"] == "Intro to Physics!"
    assert body["subject"] == "Physics"
    assert body["grade_band"] == "9-12"
    assert body["unit_count"] == 0
    assert body["topic_count"] == 0
    assert body["published_count"] == 0
    assert body["draft_count"] == 0

    row = courses.rows[0]
    assert row["origin"] == "teacher"
    assert row["owner_id"] == TEACHER_ID
    assert row["slug"]  # non-empty
    assert row["slug"].startswith("intro-to-physics-")
    assert "teaching_style" not in row  # left null at create


def test_create_course_non_teacher_gets_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot create a course."""
    sb = _make_supabase(role="student")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/courses", headers=dev_headers, json={"title": "X"}
    )
    assert r.status_code == 403


def test_create_course_rejects_empty_title(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty `title` fails Pydantic validation (422)."""
    sb = _make_supabase(role="teacher")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/courses", headers=dev_headers, json={"title": ""}
    )
    assert r.status_code == 422


# ═══ GET /v1/teacher/courses/{id} ═════════════════════════════════════════
def test_get_course_detail_returns_units_with_material_counts(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail returns units (ordered) with `material_count` + the course's
    `teaching_style`."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {
                "id": COURSE_ID,
                "title": "Physics",
                "subject": "Physics",
                "grade_band": "9-12",
                "teaching_style": "Socratic",
                "owner_id": TEACHER_ID,
            }
        ],
        units=[
            {"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "Kinematics"},
            {"id": UNIT_2_ID, "course_id": COURSE_ID, "n": 2, "name": "Forces"},
        ],
        materials=[
            {"id": "m1", "unit_id": UNIT_ID, "conversion_status": "converted"},
            {"id": "m2", "unit_id": UNIT_ID, "conversion_status": "pending"},
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/courses/{COURSE_ID}", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == COURSE_ID
    assert body["teaching_style"] == "Socratic"
    assert len(body["units"]) == 2
    by_id = {u["id"]: u for u in body["units"]}
    assert by_id[UNIT_ID]["material_count"] == 2
    assert by_id[UNIT_ID]["name"] == "Kinematics"
    assert by_id[UNIT_2_ID]["material_count"] == 0


def test_get_course_detail_other_teachers_course_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A course owned by a different teacher 404s (not 403 — no leak)."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {
                "id": COURSE_ID,
                "title": "Not Mine",
                "owner_id": OTHER_TEACHER_ID,
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/courses/{COURSE_ID}", headers=dev_headers)
    assert r.status_code == 404


def test_get_course_detail_missing_course_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown course id 404s."""
    sb = _make_supabase(role="teacher", courses=[])
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/courses/{COURSE_ID}", headers=dev_headers)
    assert r.status_code == 404


# ═══ PATCH /v1/teacher/courses/{id} ═══════════════════════════════════════
def test_patch_course_updates_teaching_style(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATCH sets `teaching_style` on the course row."""
    courses = _Table(
        [
            {
                "id": COURSE_ID,
                "title": "Physics",
                "teaching_style": None,
                "owner_id": TEACHER_ID,
            }
        ]
    )
    sb = _make_supabase(role="teacher", courses=courses)
    _wire(monkeypatch, sb)

    r = client.patch(
        f"/v1/teacher/courses/{COURSE_ID}",
        headers=dev_headers,
        json={"teaching_style": "Encouraging, lots of analogies"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "id": COURSE_ID,
        "teaching_style": "Encouraging, lots of analogies",
    }
    assert courses.rows[0]["teaching_style"] == "Encouraging, lots of analogies"


def test_patch_course_non_owned_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATCH on a course owned by another teacher 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {"id": COURSE_ID, "title": "Not Mine", "owner_id": OTHER_TEACHER_ID}
        ],
    )
    _wire(monkeypatch, sb)

    r = client.patch(
        f"/v1/teacher/courses/{COURSE_ID}",
        headers=dev_headers,
        json={"teaching_style": "X"},
    )
    assert r.status_code == 404


# ═══ POST /v1/teacher/courses/{id}/units ══════════════════════════════════
def test_create_unit_assigns_next_n(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new unit gets `n` one past the highest existing n (1,2 -> 3)."""
    units = _Table(
        [
            {"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "One"},
            {"id": UNIT_2_ID, "course_id": COURSE_ID, "n": 2, "name": "Two"},
        ],
        id_for=lambda: "new-unit-id",
    )
    sb = _make_supabase(
        role="teacher",
        courses=[{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}],
        units=units,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/courses/{COURSE_ID}/units",
        headers=dev_headers,
        json={"name": "Three"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["n"] == 3
    assert body["name"] == "Three"
    assert body["material_count"] == 0
    new_row = next(r for r in units.rows if r["name"] == "Three")
    assert new_row["n"] == 3
    assert new_row["course_id"] == COURSE_ID


def test_create_unit_first_unit_is_n1(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first unit in an empty course gets n=1."""
    units = _Table([], id_for=lambda: "new-unit-id")
    sb = _make_supabase(
        role="teacher",
        courses=[{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}],
        units=units,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/courses/{COURSE_ID}/units",
        headers=dev_headers,
        json={"name": "First"},
    )
    assert r.status_code == 201
    assert r.json()["n"] == 1


def test_create_unit_non_owned_course_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a unit under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {"id": COURSE_ID, "title": "Not Mine", "owner_id": OTHER_TEACHER_ID}
        ],
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/courses/{COURSE_ID}/units",
        headers=dev_headers,
        json={"name": "X"},
    )
    assert r.status_code == 404


# ═══ GET /v1/teacher/units/{id} ═══════════════════════════════════════════
def test_get_unit_detail_returns_materials_with_status(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit detail returns materials whose `status` is `conversion_status`."""
    sb = _make_supabase(
        role="teacher",
        courses=[{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}],
        units=[
            {"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "Kinematics"}
        ],
        materials=[
            {
                "id": MATERIAL_ID,
                "unit_id": UNIT_ID,
                "filename": "deck.pdf",
                "kind": None,
                "conversion_status": "converted",
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == UNIT_ID
    assert body["name"] == "Kinematics"
    assert body["course_id"] == COURSE_ID
    assert body["course_title"] == "Physics"
    assert len(body["materials"]) == 1
    mat = body["materials"][0]
    assert mat["id"] == MATERIAL_ID
    assert mat["filename"] == "deck.pdf"
    assert mat["status"] == "converted"


def test_get_unit_detail_non_owned_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit whose course is owned by another teacher 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {"id": COURSE_ID, "title": "Not Mine", "owner_id": OTHER_TEACHER_ID}
        ],
        units=[{"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "X"}],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 404


def test_get_unit_detail_missing_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown unit id 404s."""
    sb = _make_supabase(role="teacher", units=[])
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 404


# ═══ POST /v1/teacher/units/{id}/materials ════════════════════════════════
def test_upload_materials_ingests_and_returns_material_rows(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid upload is ingested; the response carries the material row
    shape (id/filename/kind/status)."""
    sb = _make_supabase(
        role="teacher",
        courses=[{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}],
        units=[{"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "K"}],
    )
    _wire(monkeypatch, sb)

    monkeypatch.setattr(
        "app.api.v1.teacher.ingest_material",
        lambda **_kw: IngestResult(
            material_id=MATERIAL_ID,
            conversion_status="converted",
            storage_path=f"{TEACHER_ID}/{UNIT_ID}/{MATERIAL_ID}/deck.pdf",
            normalized_pdf=f"{TEACHER_ID}/{UNIT_ID}/{MATERIAL_ID}/deck.pdf",
        ),
    )

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/materials",
        files={"files": ("deck.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    mat = body[0]
    assert mat["id"] == MATERIAL_ID
    assert mat["filename"] == "deck.pdf"
    assert mat["kind"] is None
    assert mat["status"] == "converted"


def test_upload_materials_rejects_spoofed_file_with_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that fails `validate_upload` (a `.pdf` whose body is not a PDF)
    is rejected with 400 before any ingest runs."""
    sb = _make_supabase(
        role="teacher",
        courses=[{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}],
        units=[{"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "K"}],
    )
    _wire(monkeypatch, sb)

    # ingest_material is NOT mocked — the real validate_upload must reject.
    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/materials",
        files={"files": ("evil.pdf", b"not a pdf", "application/pdf")},
        headers=dev_headers,
    )
    assert r.status_code == 400
    assert "evil.pdf" in r.json()["detail"]


def test_upload_materials_non_owned_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uploading to a unit whose course is owned by another teacher 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=[
            {"id": COURSE_ID, "title": "Not Mine", "owner_id": OTHER_TEACHER_ID}
        ],
        units=[{"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "X"}],
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/materials",
        files={"files": ("deck.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
        headers=dev_headers,
    )
    assert r.status_code == 404
