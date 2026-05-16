"""Cross-tenant RLS tests for the teacher-authored courses schema (task 1.2).

These prove the docs/teacher-authoring.md §4 "RLS" rules by exercising the
policies as the Postgres `authenticated` role with a `request.jwt.claims`
JWT — exactly how Supabase runs an anon-key + JWT client. A service-role
connection bypasses RLS and would prove nothing, so these tests open a
DIRECT Postgres connection (psycopg) and `set local role authenticated`
per transaction.

What each test proves:
  * test_pending_student_cannot_read_assigned_course / _topics —
    a 'pending' (un-approved) membership grants NO access.
  * test_active_student_cannot_read_other_class_course —
    a student active in class A cannot read class B's course.
  * test_active_student_reads_published_but_not_draft_topic —
    an active member sees 'published' teacher topics, never 'draft' ones.
  * test_teacher_cannot_read_other_teachers_classes / _materials —
    a teacher is fully walled off from another teacher's tenant.
  * test_recommended_course_topics_world_readable —
    the policy replacement did NOT regress Recommended-course visibility.

Running these REQUIRES the 20260515050000_teacher_authoring_schema.sql
migration to be applied AND a Postgres connection string in `DATABASE_URL`
(or `SUPABASE_DB_URL`). Until both are true the whole module SKIPS with a
clear reason — it is collected, never silently passed. The orchestrator
applies the migration to the cloud DB and sets DATABASE_URL to run them.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

# ─── connection / availability guard ──────────────────────────────────────
_DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

try:  # psycopg is a dev-only dep; tolerate its absence.
    import psycopg

    _HAS_PSYCOPG = True
except ImportError:  # pragma: no cover - env-dependent
    _HAS_PSYCOPG = False


def _migration_applied(conn: Any) -> bool:
    """True once the §4 schema exists — keyed on a table this migration adds."""
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.class_members')")
        return cur.fetchone()[0] is not None


def _skip_reason() -> str | None:
    """Return why the module should skip, or None when it can run."""
    if not _HAS_PSYCOPG:
        return "psycopg not installed (pip install 'psycopg[binary]')"
    if not _DB_URL:
        return (
            "DATABASE_URL / SUPABASE_DB_URL not set — RLS tests need a direct "
            "Postgres connection to `set role authenticated`"
        )
    try:
        with psycopg.connect(_DB_URL, connect_timeout=5) as conn:
            if not _migration_applied(conn):
                return (
                    "20260515050000_teacher_authoring_schema.sql not applied "
                    "yet (public.class_members missing)"
                )
    except Exception as exc:  # pragma: no cover - env-dependent
        return f"cannot reach Postgres at DATABASE_URL: {exc}"
    return None


# Evaluated once at collection time — the module is COLLECTED then skipped
# (never silently passed) when the DB / migration is not ready.
_SKIP = _skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


# ─── RLS-aware query helpers ──────────────────────────────────────────────
def _as_user(conn: Any, user_id: str, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    """Run `sql` inside a tx as the `authenticated` role with a JWT for `user_id`.

    Each call is its own transaction: `set local` scopes the role + claims to
    that tx, so policies see `auth.uid()` = `user_id`. Returns the rows.
    """
    claims = (
        '{"sub":"' + user_id + '","role":"authenticated"}'
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("set local role authenticated")
        cur.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except psycopg.ProgrammingError:
            return []


def _service(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> None:
    """Run a privileged statement (no RLS) — used only to SEED fixtures."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(sql, params)


# ─── fixtures: a two-tenant world ─────────────────────────────────────────
@pytest.fixture(scope="module")
def db() -> Iterator[Any]:
    """A service-role psycopg connection (bypasses RLS) for seeding."""
    conn = psycopg.connect(_DB_URL, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def world(db: Any) -> Iterator[dict[str, str]]:
    """Seed two isolated teacher tenants + students, yield their ids, clean up.

    Tenant A: teacher_a owns course_a (+ unit_a, published topic + draft topic,
              + lesson_material_a) and class_a. student_active is an ACTIVE
              member of class_a (which is assigned course_a); student_pending
              is a PENDING member of class_a.
    Tenant B: teacher_b owns course_b and class_b — fully separate.
    Plus one Recommended course to prove the world-read policy still holds.
    """
    ids = {k: str(uuid.uuid4()) for k in (
        "teacher_a", "teacher_b", "student_active", "student_pending",
        "course_a", "course_b", "course_rec",
        "unit_a", "unit_b", "unit_rec",
        "topic_pub", "topic_draft", "topic_rec",
        "class_a", "class_b", "material_a",
    )}

    # auth.users rows first — profiles.id FK-references them.
    for who in ("teacher_a", "teacher_b", "student_active", "student_pending"):
        _service(
            db,
            "insert into auth.users (id, email) values (%s, %s) "
            "on conflict (id) do nothing",
            (ids[who], f"rls-{who}-{ids[who][:8]}@edutest-qa.dev"),
        )
    # profiles (the handle_new_user trigger may also create these — upsert).
    for who, role in (
        ("teacher_a", "teacher"), ("teacher_b", "teacher"),
        ("student_active", "student"), ("student_pending", "student"),
    ):
        _service(
            db,
            "insert into public.profiles (id, role) values (%s, %s) "
            "on conflict (id) do update set role = excluded.role",
            (ids[who], role),
        )

    # courses — two teacher-owned, one recommended.
    _service(
        db,
        "insert into public.courses (id, slug, title, origin, owner_id) "
        "values (%s, %s, %s, 'teacher', %s)",
        (ids["course_a"], f"rls-course-a-{ids['course_a'][:8]}", "Tenant A Course", ids["teacher_a"]),
    )
    _service(
        db,
        "insert into public.courses (id, slug, title, origin, owner_id) "
        "values (%s, %s, %s, 'teacher', %s)",
        (ids["course_b"], f"rls-course-b-{ids['course_b'][:8]}", "Tenant B Course", ids["teacher_b"]),
    )
    _service(
        db,
        "insert into public.courses (id, slug, title, origin) "
        "values (%s, %s, %s, 'recommended')",
        (ids["course_rec"], f"rls-course-rec-{ids['course_rec'][:8]}", "Recommended Course"),
    )

    # units.
    for unit, course in (
        ("unit_a", "course_a"), ("unit_b", "course_b"), ("unit_rec", "course_rec"),
    ):
        _service(
            db,
            "insert into public.units (id, course_id, n, name) values (%s, %s, 1, %s)",
            (ids[unit], ids[course], f"{unit} name"),
        )

    # topics — a published + a draft teacher topic, plus a recommended topic.
    _service(
        db,
        "insert into public.topics (id, unit_id, n, name, status) "
        "values (%s, %s, 1, 'Published Topic', 'published')",
        (ids["topic_pub"], ids["unit_a"]),
    )
    _service(
        db,
        "insert into public.topics (id, unit_id, n, name, status) "
        "values (%s, %s, 2, 'Draft Topic', 'draft')",
        (ids["topic_draft"], ids["unit_a"]),
    )
    _service(
        db,
        "insert into public.topics (id, unit_id, n, name) "
        "values (%s, %s, 1, 'Recommended Topic')",
        (ids["topic_rec"], ids["unit_rec"]),
    )

    # a lesson material in tenant A (cross-tenant denial target).
    _service(
        db,
        "insert into public.lesson_materials (id, unit_id, kind, filename) "
        "values (%s, %s, 'slides', 'tenant-a.pdf')",
        (ids["material_a"], ids["unit_a"]),
    )

    # classes — A owned by teacher_a, B by teacher_b.
    _service(
        db,
        "insert into public.classes (id, teacher_id, name, join_code) "
        "values (%s, %s, 'Class A', %s)",
        (ids["class_a"], ids["teacher_a"], f"RLSA-{ids['class_a'][:5]}"),
    )
    _service(
        db,
        "insert into public.classes (id, teacher_id, name, join_code) "
        "values (%s, %s, 'Class B', %s)",
        (ids["class_b"], ids["teacher_b"], f"RLSB-{ids['class_b'][:5]}"),
    )
    # class_a is assigned course_a.
    _service(
        db,
        "insert into public.class_courses (class_id, course_id, assigned_at) "
        "values (%s, %s, now())",
        (ids["class_a"], ids["course_a"]),
    )
    # student_active: ACTIVE in class_a; student_pending: PENDING in class_a.
    _service(
        db,
        "insert into public.class_members (class_id, student_id, status, requested_at) "
        "values (%s, %s, 'active', now())",
        (ids["class_a"], ids["student_active"]),
    )
    _service(
        db,
        "insert into public.class_members (class_id, student_id, status, requested_at) "
        "values (%s, %s, 'pending', now())",
        (ids["class_a"], ids["student_pending"]),
    )
    db.commit()

    try:
        yield ids
    finally:
        # Tear down — cascades clean most children; courses/classes need
        # explicit deletes (no cascade from profiles by design).
        for tbl, col in (
            ("class_members", "class_id"), ("class_courses", "class_id"),
        ):
            for cid in (ids["class_a"], ids["class_b"]):
                _service(db, f"delete from public.{tbl} where {col} = %s", (cid,))
        for cid in (ids["class_a"], ids["class_b"]):
            _service(db, "delete from public.classes where id = %s", (cid,))
        for cid in (ids["course_a"], ids["course_b"], ids["course_rec"]):
            _service(db, "delete from public.courses where id = %s", (cid,))
        for who in ("teacher_a", "teacher_b", "student_active", "student_pending"):
            _service(db, "delete from public.profiles where id = %s", (ids[who],))
            _service(db, "delete from auth.users where id = %s", (ids[who],))
        db.commit()


# ─── tests: student-side cross-tenant denial ──────────────────────────────
def test_pending_student_cannot_read_assigned_course(db: Any, world: dict[str, str]) -> None:
    """A 'pending' membership grants NO access to the class's teacher course."""
    rows = _as_user(
        db, world["student_pending"],
        "select id from public.courses where id = %s", (world["course_a"],),
    )
    assert rows == [], "pending student must not see the assigned teacher course"


def test_pending_student_cannot_read_published_topic(db: Any, world: dict[str, str]) -> None:
    """A 'pending' membership cannot read even a published teacher topic."""
    rows = _as_user(
        db, world["student_pending"],
        "select id from public.topics where id = %s", (world["topic_pub"],),
    )
    assert rows == [], "pending student must not see any teacher-course topic"


def test_active_student_cannot_read_other_class_course(db: Any, world: dict[str, str]) -> None:
    """A student active in class A cannot read class B's (other tenant) course."""
    rows = _as_user(
        db, world["student_active"],
        "select id from public.courses where id = %s", (world["course_b"],),
    )
    assert rows == [], "active student must not see another teacher's course"


def test_active_student_reads_published_but_not_draft_topic(
    db: Any, world: dict[str, str]
) -> None:
    """An active member sees 'published' teacher topics, never 'draft' ones."""
    published = _as_user(
        db, world["student_active"],
        "select id from public.topics where id = %s", (world["topic_pub"],),
    )
    assert len(published) == 1, "active student SHOULD see a published teacher topic"

    draft = _as_user(
        db, world["student_active"],
        "select id from public.topics where id = %s", (world["topic_draft"],),
    )
    assert draft == [], "active student must NOT see a draft teacher topic"


def test_active_student_can_read_assigned_course(db: Any, world: dict[str, str]) -> None:
    """The positive path: an active member CAN read the assigned teacher course."""
    rows = _as_user(
        db, world["student_active"],
        "select id from public.courses where id = %s", (world["course_a"],),
    )
    assert len(rows) == 1, "active member should see the assigned teacher course"


# ─── tests: teacher-side cross-tenant denial ──────────────────────────────
def test_teacher_cannot_read_other_teachers_class(db: Any, world: dict[str, str]) -> None:
    """teacher_a cannot read teacher_b's class."""
    rows = _as_user(
        db, world["teacher_a"],
        "select id from public.classes where id = %s", (world["class_b"],),
    )
    assert rows == [], "a teacher must not see another teacher's class"


def test_teacher_cannot_read_other_teachers_materials(db: Any, world: dict[str, str]) -> None:
    """teacher_b cannot read teacher_a's lesson_materials (no teacher_id col —
    proves the unit -> course -> owner_id join helper walls tenants off)."""
    rows = _as_user(
        db, world["teacher_b"],
        "select id from public.lesson_materials where id = %s", (world["material_a"],),
    )
    assert rows == [], "a teacher must not see another teacher's lesson material"


def test_teacher_cannot_read_other_teachers_course(db: Any, world: dict[str, str]) -> None:
    """teacher_b cannot read teacher_a's (unpublished-irrelevant) course."""
    rows = _as_user(
        db, world["teacher_b"],
        "select id from public.courses where id = %s", (world["course_a"],),
    )
    assert rows == [], "a teacher must not see another teacher's course"


def test_teacher_can_read_own_material(db: Any, world: dict[str, str]) -> None:
    """The positive path: teacher_a CAN read their own lesson material."""
    rows = _as_user(
        db, world["teacher_a"],
        "select id from public.lesson_materials where id = %s", (world["material_a"],),
    )
    assert len(rows) == 1, "the owning teacher should see their own material"


# ─── tests: no regression of Recommended-course visibility ────────────────
def test_recommended_course_topics_world_readable(db: Any, world: dict[str, str]) -> None:
    """Replacing topics_read_all must NOT break Recommended-course reads — a
    student with no class membership still reads recommended courses + topics."""
    course = _as_user(
        db, world["student_pending"],
        "select id from public.courses where id = %s", (world["course_rec"],),
    )
    assert len(course) == 1, "recommended courses stay world-readable"

    topic = _as_user(
        db, world["student_pending"],
        "select id from public.topics where id = %s", (world["topic_rec"],),
    )
    assert len(topic) == 1, "recommended-course topics stay world-readable"
