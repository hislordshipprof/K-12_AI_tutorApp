"""Tests for the class-management endpoints (task 3.2).

Covers the teacher class-management screen backend (`teacher-authoring.md`
§9/§14):

  * `POST /v1/teacher/classes` — create a class with a generated join code;
    a non-teacher is 403'd.
  * `GET /v1/teacher/classes/{id}` — roster + pending split; a class owned
    by a different teacher 404s.
  * `POST /v1/teacher/classes/{id}/members/{sid}/approve` — flips a pending
    member to active and records `approved_by`/`approved_at` (the §14
    consent checkpoint); approving in a non-owned class 404s.
  * `DELETE /v1/teacher/classes/{id}/members/{sid}` — removes the row (204);
    a non-owned class 404s.
  * `POST /v1/classes/join` — valid code creates a pending membership;
    an unknown code 404s; re-joining does not duplicate.

Supabase is mocked: a MagicMock client whose `.table(name)` dispatches to a
per-table builder, mirroring `test_teacher_lists.py`. A small stateful
table fake is used where an endpoint reads back what it just wrote.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# `dev_headers` authenticates as this id (see conftest.py).
TEACHER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TEACHER_ID = "00000000-0000-0000-0000-0000000000ff"
CLASS_ID = "11111111-1111-1111-1111-111111111111"
STUDENT_ID = "22222222-2222-2222-2222-222222222222"
STUDENT_2_ID = "33333333-3333-3333-3333-333333333333"


# ─── select-chain mock (read-only tables) ─────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A MagicMock that mimics a Supabase select builder chain."""
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "in_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


class _ProfilesTable:
    """A `supabase.table("profiles")` stand-in serving two query shapes.

    A `.select("role").eq("id", caller)` role lookup yields `[{"role": …}]`;
    a `.select("id,full_name").in_("id", …)` lookup yields the name rows.
    The shape is picked off the `select` column list, mirroring Postgres.
    """

    def __init__(self, role: str, name_rows: list[dict[str, Any]]) -> None:
        self._role = role
        self._name_rows = [dict(r) for r in name_rows]

    def select(self, columns: str = "*") -> "_ProfilesTable":
        self._wants_role = "role" in columns and "full_name" not in columns
        return self

    def eq(self, *_a: Any) -> "_ProfilesTable":
        return self

    def in_(self, *_a: Any) -> "_ProfilesTable":
        return self

    def limit(self, _n: int) -> "_ProfilesTable":
        return self

    def execute(self) -> MagicMock:
        if self._wants_role:
            return MagicMock(data=[{"role": self._role}])
        return MagicMock(data=[dict(r) for r in self._name_rows])


# ─── stateful class_members table fake ────────────────────────────────────
class _MembersTable:
    """A minimal stand-in for `supabase.table("class_members")`.

    Models the select / insert / update / delete chains the endpoints use
    against an in-memory list, with `.eq()` filters applied on execute, so
    a read after a write reflects the change (like Postgres).
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]

    def select(self, _columns: str = "*") -> "_MembersTable":
        self._mode = "select"
        self._filters: dict[str, Any] = {}
        return self

    def insert(self, payload: dict[str, Any]) -> "_MembersTable":
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> "_MembersTable":
        self._mode = "update"
        self._payload = payload
        self._filters = {}
        return self

    def delete(self) -> "_MembersTable":
        self._mode = "delete"
        self._filters = {}
        return self

    def eq(self, key: str, value: Any) -> "_MembersTable":
        self._filters[key] = value
        return self

    def in_(self, _key: str, _values: Any) -> "_MembersTable":
        return self

    def limit(self, _n: int) -> "_MembersTable":
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(str(row.get(k)) == str(v) for k, v in self._filters.items())

    def execute(self) -> MagicMock:
        if self._mode == "select":
            return MagicMock(data=[r for r in self.rows if self._matches(r)])
        if self._mode == "insert":
            self.rows.append(dict(self._payload))
            return MagicMock(data=[dict(self._payload)])
        if self._mode == "update":
            hit = [r for r in self.rows if self._matches(r)]
            for r in hit:
                r.update(self._payload)
            return MagicMock(data=[dict(r) for r in hit])
        if self._mode == "delete":
            hit = [r for r in self.rows if self._matches(r)]
            self.rows = [r for r in self.rows if not self._matches(r)]
            return MagicMock(data=[dict(r) for r in hit])
        return MagicMock(data=[])


def _make_supabase(
    *,
    role: str,
    classes: list[dict[str, Any]] | None = None,
    members: _MembersTable | list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    class_courses: list[dict[str, Any]] | None = None,
    courses: list[dict[str, Any]] | None = None,
    emails: dict[str, str] | None = None,
) -> MagicMock:
    """Build a Supabase mock dispatching each table name to its builder.

    `profiles` is special: a role lookup (`.select("role")`) must return
    the caller's role, while a `.in_("id", ...)` lookup returns full_name
    rows. The fake below answers both off the same builder.
    """
    if isinstance(members, list) or members is None:
        members_tbl: _MembersTable = _MembersTable(members or [])
    else:
        members_tbl = members

    chains: dict[str, Any] = {
        "classes": _select_chain(classes or []),
        "class_members": members_tbl,
        "profiles": _ProfilesTable(role, profiles or []),
        "class_courses": _select_chain(class_courses or []),
        "courses": _select_chain(courses or []),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: chains.get(name, _select_chain([]))

    # auth.admin.get_user_by_id — best-effort email lookup.
    def _get_user(sid: str) -> MagicMock:
        addr = (emails or {}).get(str(sid))
        if addr is None:
            raise RuntimeError("no such user")
        return MagicMock(user=MagicMock(email=addr))

    client.auth.admin.get_user_by_id.side_effect = _get_user
    return client


def _wire(monkeypatch: pytest.MonkeyPatch, sb: MagicMock) -> None:
    """Point the security + both class routers at the mock client."""
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.classes.get_supabase", lambda: sb)


# ═══ POST /v1/teacher/classes ═════════════════════════════════════════════
def test_create_class_returns_class_with_generated_join_code(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a class returns the class with a generated unique join code
    and zero counts; the join code carries the subject-derived prefix."""

    class _ClassesInsert:
        """classes table: select -> no collision; insert -> echoes the row."""

        def select(self, _c: str = "*") -> "_ClassesInsert":
            self._mode = "select"
            return self

        def insert(self, payload: dict[str, Any]) -> "_ClassesInsert":
            self._mode = "insert"
            self._payload = {**payload, "id": CLASS_ID}
            return self

        def eq(self, *_a: Any) -> "_ClassesInsert":
            return self

        def limit(self, _n: int) -> "_ClassesInsert":
            return self

        def execute(self) -> MagicMock:
            if self._mode == "insert":
                return MagicMock(data=[dict(self._payload)])
            return MagicMock(data=[])  # no join_code collision

    sb = _make_supabase(role="teacher")
    sb.table.side_effect = lambda name: (
        _ClassesInsert()
        if name == "classes"
        else _select_chain([{"role": "teacher"}])
    )
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/classes",
        headers=dev_headers,
        json={"name": "Period 1 Physics", "subject": "Physics"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == CLASS_ID
    assert body["name"] == "Period 1 Physics"
    assert body["subject"] == "Physics"
    assert body["student_count"] == 0
    assert body["pending_count"] == 0
    # Prefix = first 4 letters of subject upper-cased, then "-XXXX".
    assert body["join_code"].startswith("PHYS-")
    assert len(body["join_code"]) == 9


def test_create_class_non_teacher_gets_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot create a class."""
    sb = _make_supabase(role="student")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/classes", headers=dev_headers, json={"name": "X"}
    )
    assert r.status_code == 403


def test_create_class_rejects_empty_name(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty `name` fails Pydantic validation (422)."""
    sb = _make_supabase(role="teacher")
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/teacher/classes", headers=dev_headers, json={"name": ""}
    )
    assert r.status_code == 422


# ═══ GET /v1/teacher/classes/{id} ═════════════════════════════════════════
def test_get_class_detail_splits_roster_and_pending(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail returns active members as `roster` and pending members as
    `pending`, each with name + best-effort email."""
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Period 1 Physics",
                "subject": "Physics",
                "join_code": "PHYS-7K2M",
                "teacher_id": TEACHER_ID,
                "archived": False,
            }
        ],
        members=[
            {
                "class_id": CLASS_ID,
                "student_id": STUDENT_ID,
                "status": "active",
                "requested_at": "2026-05-01T00:00:00+00:00",
                "approved_at": "2026-05-02T00:00:00+00:00",
            },
            {
                "class_id": CLASS_ID,
                "student_id": STUDENT_2_ID,
                "status": "pending",
                "requested_at": "2026-05-03T00:00:00+00:00",
                "approved_at": None,
            },
        ],
        profiles=[
            {"id": STUDENT_ID, "full_name": "Ada Lovelace"},
            {"id": STUDENT_2_ID, "full_name": "Alan Turing"},
        ],
        emails={STUDENT_ID: "ada@example.com"},
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/classes/{CLASS_ID}", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == CLASS_ID
    assert body["join_code"] == "PHYS-7K2M"
    assert body["courses"] == []

    assert len(body["roster"]) == 1
    active = body["roster"][0]
    assert active["student_id"] == STUDENT_ID
    assert active["name"] == "Ada Lovelace"
    assert active["email"] == "ada@example.com"
    assert active["joined_at"] == "2026-05-02T00:00:00+00:00"

    assert len(body["pending"]) == 1
    pend = body["pending"][0]
    assert pend["student_id"] == STUDENT_2_ID
    assert pend["name"] == "Alan Turing"
    # email lookup failed for this student -> None, not a crash.
    assert pend["email"] is None
    assert pend["requested_at"] == "2026-05-03T00:00:00+00:00"


def test_get_class_detail_other_teachers_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A class owned by a different teacher 404s (not 403 — no leak)."""
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Not Mine",
                "subject": None,
                "join_code": "CLAS-AAAA",
                "teacher_id": OTHER_TEACHER_ID,
                "archived": False,
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/classes/{CLASS_ID}", headers=dev_headers)
    assert r.status_code == 404


def test_get_class_detail_missing_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown class id 404s."""
    sb = _make_supabase(role="teacher", classes=[])
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/classes/{CLASS_ID}", headers=dev_headers)
    assert r.status_code == 404


# ═══ POST /v1/teacher/classes/{id}/members/{sid}/approve ══════════════════
def test_approve_member_flips_pending_to_active(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approving a pending member sets status=active and records
    approved_by + approved_at (the §14 consent checkpoint)."""
    members = _MembersTable(
        [
            {
                "class_id": CLASS_ID,
                "student_id": STUDENT_ID,
                "status": "pending",
                "approved_by": None,
                "approved_at": None,
            }
        ]
    )
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Period 1",
                "subject": "Physics",
                "join_code": "PHYS-7K2M",
                "teacher_id": TEACHER_ID,
                "archived": False,
            }
        ],
        members=members,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/members/{STUDENT_ID}/approve",
        headers=dev_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    row = members.rows[0]
    assert row["status"] == "active"
    assert row["approved_by"] == TEACHER_ID
    assert row["approved_at"] is not None


def test_approve_member_unknown_membership_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approving a student with no membership row 404s."""
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Period 1",
                "subject": "Physics",
                "join_code": "PHYS-7K2M",
                "teacher_id": TEACHER_ID,
                "archived": False,
            }
        ],
        members=[],
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/members/{STUDENT_ID}/approve",
        headers=dev_headers,
    )
    assert r.status_code == 404


def test_approve_member_in_non_owned_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approving in a class owned by another teacher 404s."""
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Not Mine",
                "subject": None,
                "join_code": "CLAS-AAAA",
                "teacher_id": OTHER_TEACHER_ID,
                "archived": False,
            }
        ],
        members=[
            {
                "class_id": CLASS_ID,
                "student_id": STUDENT_ID,
                "status": "pending",
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/classes/{CLASS_ID}/members/{STUDENT_ID}/approve",
        headers=dev_headers,
    )
    assert r.status_code == 404


# ═══ DELETE /v1/teacher/classes/{id}/members/{sid} ════════════════════════
def test_remove_member_deletes_row_204(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing a member deletes the class_members row and returns 204."""
    members = _MembersTable(
        [
            {"class_id": CLASS_ID, "student_id": STUDENT_ID, "status": "active"},
            {"class_id": CLASS_ID, "student_id": STUDENT_2_ID, "status": "pending"},
        ]
    )
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Period 1",
                "subject": "Physics",
                "join_code": "PHYS-7K2M",
                "teacher_id": TEACHER_ID,
                "archived": False,
            }
        ],
        members=members,
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/classes/{CLASS_ID}/members/{STUDENT_ID}",
        headers=dev_headers,
    )
    assert r.status_code == 204
    assert [m["student_id"] for m in members.rows] == [STUDENT_2_ID]


def test_remove_member_in_non_owned_class_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing a member from a non-owned class 404s and deletes nothing."""
    members = _MembersTable(
        [{"class_id": CLASS_ID, "student_id": STUDENT_ID, "status": "active"}]
    )
    sb = _make_supabase(
        role="teacher",
        classes=[
            {
                "id": CLASS_ID,
                "name": "Not Mine",
                "subject": None,
                "join_code": "CLAS-AAAA",
                "teacher_id": OTHER_TEACHER_ID,
                "archived": False,
            }
        ],
        members=members,
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/classes/{CLASS_ID}/members/{STUDENT_ID}",
        headers=dev_headers,
    )
    assert r.status_code == 404
    assert len(members.rows) == 1  # untouched


# ═══ POST /v1/classes/join ════════════════════════════════════════════════
def test_join_class_creates_pending_membership(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid join code creates a pending class_members row for the caller."""
    members = _MembersTable([])
    sb = _make_supabase(
        role="student",
        classes=[
            {"id": CLASS_ID, "name": "Period 1 Physics", "join_code": "PHYS-7K2M"}
        ],
        members=members,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/classes/join", headers=dev_headers, json={"join_code": "phys-7k2m"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["class_id"] == CLASS_ID
    assert body["class_name"] == "Period 1 Physics"
    assert body["status"] == "pending"

    assert len(members.rows) == 1
    row = members.rows[0]
    assert row["class_id"] == CLASS_ID
    assert row["student_id"] == TEACHER_ID  # dev_headers caller
    assert row["status"] == "pending"


def test_join_class_unknown_code_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown join code 404s."""
    sb = _make_supabase(role="student", classes=[], members=[])
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/classes/join", headers=dev_headers, json={"join_code": "NOPE-9999"}
    )
    assert r.status_code == 404


def test_join_class_is_idempotent(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Joining a class the caller already belongs to does not duplicate the
    membership and does not downgrade an active membership to pending."""
    members = _MembersTable(
        [{"class_id": CLASS_ID, "student_id": TEACHER_ID, "status": "active"}]
    )
    sb = _make_supabase(
        role="student",
        classes=[
            {"id": CLASS_ID, "name": "Period 1 Physics", "join_code": "PHYS-7K2M"}
        ],
        members=members,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        "/v1/classes/join", headers=dev_headers, json={"join_code": "PHYS-7K2M"}
    )
    assert r.status_code == 200
    # Existing active membership is returned unchanged — not downgraded.
    assert r.json()["status"] == "active"
    assert len(members.rows) == 1  # no duplicate row
    assert members.rows[0]["status"] == "active"
