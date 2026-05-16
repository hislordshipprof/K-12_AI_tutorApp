"""Tests for the topic / lesson-management endpoints (task 3.5).

Wires the Phase 2 generate/validate service layer into HTTP
(`teacher-authoring.md` §4/§6/§10):

  * `GET /v1/teacher/topics/{id}` — the topic's lesson, its `topic_versions`
    (newest-first, each with its per-version `validation` + an `active`
    flag) and its latest `kind='generate'` job; non-owned topic 404s.
  * `PATCH /v1/teacher/topics/{id}` — updates `design_notes` and / or
    hand-edited `content`; a `content` edit mirrors into the active version.
  * `POST /v1/teacher/topics/{id}/generate` — enqueues a `generate`
    `pipeline_jobs` row and runs it in the background; returns an existing
    in-flight job instead of starting a second (§13).
  * `POST /v1/teacher/topics/{id}/versions/{vid}/activate` — sets
    `active_version_id` + mirrors the version's `content`.
  * `DELETE /v1/teacher/topics/{id}/versions/{vid}` — deletes a non-active
    version (204); 400 on deleting the active one.
  * `POST /v1/teacher/topics/{id}/publish` — the §6 publish gate: 200 only
    when the active version's `validation.passed` is True.
  * `GET /v1/teacher/units/{id}` — now also carries `topics`.

Supabase is mocked with the same per-table builder / stateful `_Table`
fake as `test_segmentation.py`. `run_job` is patched so no background work
touches Gemini or a real DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

TEACHER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TEACHER_ID = "00000000-0000-0000-0000-0000000000ff"
COURSE_ID = "11111111-1111-1111-1111-111111111111"
UNIT_ID = "22222222-2222-2222-2222-222222222222"
TOPIC_ID = "33333333-3333-3333-3333-333333333333"
V1_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
V2_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
JOB_ID = "66666666-6666-6666-6666-666666666666"


# ─── select-chain mock (read-only tables) ─────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A MagicMock that mimics a Supabase select builder chain."""
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "in_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


# ─── stateful generic table fake (mirrors test_segmentation._Table) ───────
class _Table:
    """A minimal stateful stand-in for a Supabase table.

    Models select / insert / update / delete chains against an in-memory
    list, with `.eq()` / `.in_()` filters applied on execute, so a read
    after a write reflects the change.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in rows]

    def select(self, _columns: str = "*") -> "_Table":
        self._mode = "select"
        self._filters: dict[str, Any] = {}
        self._in: tuple[str, list[str]] | None = None
        return self

    def insert(self, payload: dict[str, Any]) -> "_Table":
        self._mode = "insert"
        self._payload = dict(payload)
        return self

    def update(self, payload: dict[str, Any]) -> "_Table":
        self._mode = "update"
        self._payload = dict(payload)
        self._filters = {}
        self._in = None
        return self

    def delete(self) -> "_Table":
        self._mode = "delete"
        self._filters = {}
        self._in = None
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
            if "id" not in row or row["id"] is None:
                row["id"] = "generated-id"
            self.rows.append(row)
            return MagicMock(data=[dict(row)])
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
    courses: list[dict[str, Any]] | None = None,
    units: list[dict[str, Any]] | None = None,
    topics: _Table | list[dict[str, Any]] | None = None,
    topic_versions: _Table | list[dict[str, Any]] | None = None,
    pipeline_jobs: _Table | list[dict[str, Any]] | None = None,
    materials: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock dispatching each table name to its builder."""

    def _tbl(value: Any) -> _Table:
        return value if isinstance(value, _Table) else _Table(value or [])

    chains: dict[str, Any] = {
        "courses": _Table(courses or []),
        "units": _Table(units or []),
        "topics": _tbl(topics),
        "topic_versions": _tbl(topic_versions),
        "pipeline_jobs": _tbl(pipeline_jobs),
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


def _owned_course() -> list[dict[str, Any]]:
    return [{"id": COURSE_ID, "title": "Physics", "owner_id": TEACHER_ID}]


def _other_course() -> list[dict[str, Any]]:
    return [{"id": COURSE_ID, "title": "Not Mine", "owner_id": OTHER_TEACHER_ID}]


def _unit() -> list[dict[str, Any]]:
    return [{"id": UNIT_ID, "course_id": COURSE_ID, "n": 1, "name": "Kinematics"}]


def _topic(**over: Any) -> dict[str, Any]:
    base = {
        "id": TOPIC_ID,
        "unit_id": UNIT_ID,
        "n": 1,
        "name": "Velocity",
        "summary": "What velocity is.",
        "content": [],
        "status": "draft",
        "design_notes": None,
        "active_version_id": None,
    }
    base.update(over)
    return base


def _version(vid: str, *, validation: Any = None) -> dict[str, Any]:
    return {
        "id": vid,
        "topic_id": TOPIC_ID,
        "content": [{"tts": "hi", "html": "hi", "dur": "00:00"}],
        "label": f"v-{vid[:1]}",
        "created_at": f"2026-05-16T00:00:0{vid[:1] != 'a' and 1 or 0}Z",
        "validation": validation,
    }


_PASS_VALIDATION = {"passed": True, "covered": 3, "total": 3, "gaps": []}
_FAIL_VALIDATION = {
    "passed": False,
    "covered": 1,
    "total": 3,
    "gaps": [
        {
            "section": "Velocity",
            "key_point": "speed has direction",
            "verdict": "missing",
            "detail": "not taught",
        }
    ],
}


# ═══ GET /v1/teacher/topics/{id} ══════════════════════════════════════════
def test_get_topic_detail_returns_versions_job_and_active_flag(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The topic detail carries its versions (newest-first, with `validation`
    + an `active` flag) and its latest generate job."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic(active_version_id=V2_ID, status="draft")],
        topic_versions=[
            _version(V1_ID, validation=_FAIL_VALIDATION),
            _version(V2_ID, validation=_PASS_VALIDATION),
        ],
        pipeline_jobs=[
            {
                "id": JOB_ID,
                "kind": "generate",
                "topic_id": TOPIC_ID,
                "status": "succeeded",
                "stage": "validating",
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/topics/{TOPIC_ID}", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == TOPIC_ID
    assert body["unit_id"] == UNIT_ID
    assert body["unit_name"] == "Kinematics"
    assert body["course_id"] == COURSE_ID
    assert body["active_version_id"] == V2_ID
    assert body["generate_job"] == {
        "id": JOB_ID,
        "status": "succeeded",
        "stage": "validating",
    }
    assert len(body["versions"]) == 2
    active = {v["id"]: v["active"] for v in body["versions"]}
    assert active == {V1_ID: False, V2_ID: True}
    by_id = {v["id"]: v for v in body["versions"]}
    assert by_id[V2_ID]["validation"]["passed"] is True
    assert by_id[V1_ID]["validation"]["passed"] is False


def test_get_topic_detail_generate_job_null_when_none(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A topic that has never been generated reports `generate_job: null`."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic()],
        topic_versions=[],
        pipeline_jobs=[],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/topics/{TOPIC_ID}", headers=dev_headers)
    assert r.status_code == 200
    assert r.json()["generate_job"] is None
    assert r.json()["versions"] == []


def test_get_topic_detail_non_owned_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A topic under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        topics=[_topic()],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/topics/{TOPIC_ID}", headers=dev_headers)
    assert r.status_code == 404


def test_get_topic_detail_missing_topic_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-existent topic id 404s with `topic not found`."""
    sb = _make_supabase(role="teacher", courses=_owned_course(), units=_unit())
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/topics/{TOPIC_ID}", headers=dev_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "topic not found"


# ═══ PATCH /v1/teacher/topics/{id} ════════════════════════════════════════
def test_patch_topic_updates_design_notes(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `design_notes` patch writes the field onto the topic."""
    topics = _Table([_topic()])
    sb = _make_supabase(
        role="teacher", courses=_owned_course(), units=_unit(), topics=topics
    )
    _wire(monkeypatch, sb)

    r = client.patch(
        f"/v1/teacher/topics/{TOPIC_ID}",
        headers=dev_headers,
        json={"design_notes": "Lead with a real-world example."},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert topics.rows[0]["design_notes"] == "Lead with a real-world example."


def test_patch_topic_content_mirrors_to_active_version(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `content` patch updates `topics.content` AND the active version's
    `topic_versions.content` (the §4 invariant)."""
    topics = _Table([_topic(active_version_id=V1_ID)])
    versions = _Table([_version(V1_ID)])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=topics,
        topic_versions=versions,
    )
    _wire(monkeypatch, sb)

    new_content = [
        {"tts": "edited", "html": "edited", "dur": "00:00"},
        {"tts": "edited 2", "html": "edited 2", "dur": "00:05"},
    ]
    r = client.patch(
        f"/v1/teacher/topics/{TOPIC_ID}",
        headers=dev_headers,
        json={"content": new_content},
    )
    assert r.status_code == 200
    assert topics.rows[0]["content"] == new_content
    assert versions.rows[0]["content"] == new_content


def test_patch_topic_non_owned_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching a topic under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        topics=[_topic()],
    )
    _wire(monkeypatch, sb)

    r = client.patch(
        f"/v1/teacher/topics/{TOPIC_ID}",
        headers=dev_headers,
        json={"design_notes": "x"},
    )
    assert r.status_code == 404


# ═══ POST /v1/teacher/topics/{id}/generate ════════════════════════════════
def test_generate_enqueues_job_and_returns_job_id(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generating a topic inserts a queued `generate` job and returns its
    `job_id`; the background `run_job` is a patched no-op (no Gemini)."""
    jobs = _Table([])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic()],
        pipeline_jobs=jobs,
    )
    _wire(monkeypatch, sb)
    run_job_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.teacher.run_job", run_job_mock)

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/generate", headers=dev_headers
    )
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["status"] == "queued"

    assert len(jobs.rows) == 1
    row = jobs.rows[0]
    assert row["kind"] == "generate"
    assert row["topic_id"] == TOPIC_ID
    assert row["status"] == "queued"
    assert row["stage"] is None
    assert row["id"] == body["job_id"]


def test_generate_returns_inflight_job_without_inserting(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `running` generate job already exists -> it is returned and NO new
    `pipeline_jobs` row is inserted (§13 — one in-flight per topic)."""
    jobs = _Table(
        [
            {
                "id": JOB_ID,
                "kind": "generate",
                "topic_id": TOPIC_ID,
                "status": "running",
                "stage": "generating",
            }
        ]
    )
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic()],
        pipeline_jobs=jobs,
    )
    _wire(monkeypatch, sb)
    run_job_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.teacher.run_job", run_job_mock)

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/generate", headers=dev_headers
    )
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"] == JOB_ID
    assert body["status"] == "running"
    assert len(jobs.rows) == 1


def test_generate_non_owned_topic_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generating a topic under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        topics=[_topic()],
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/generate", headers=dev_headers
    )
    assert r.status_code == 404


def test_generate_non_teacher_is_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot enqueue a generate job."""
    sb = _make_supabase(role="student")
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/generate", headers=dev_headers
    )
    assert r.status_code == 403


# ═══ POST /v1/teacher/topics/{id}/versions/{vid}/activate ═════════════════
def test_activate_version_sets_active_and_mirrors_content(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Activating a version sets `active_version_id` and mirrors its
    `content` into `topics.content`."""
    topics = _Table([_topic(active_version_id=V1_ID)])
    v2_content = [{"tts": "v2", "html": "v2", "dur": "00:00"}]
    versions = _Table([_version(V1_ID), {**_version(V2_ID), "content": v2_content}])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=topics,
        topic_versions=versions,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/versions/{V2_ID}/activate",
        headers=dev_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert topics.rows[0]["active_version_id"] == V2_ID
    assert topics.rows[0]["content"] == v2_content


def test_activate_version_wrong_topic_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Activating a version that belongs to another topic 404s."""
    versions = _Table([{**_version(V1_ID), "topic_id": "other-topic"}])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic()],
        topic_versions=versions,
    )
    _wire(monkeypatch, sb)

    r = client.post(
        f"/v1/teacher/topics/{TOPIC_ID}/versions/{V1_ID}/activate",
        headers=dev_headers,
    )
    assert r.status_code == 404


# ═══ DELETE /v1/teacher/topics/{id}/versions/{vid} ════════════════════════
def test_delete_non_active_version_is_204(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a non-active version removes the row and returns 204."""
    versions = _Table([_version(V1_ID), _version(V2_ID)])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic(active_version_id=V2_ID)],
        topic_versions=versions,
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/topics/{TOPIC_ID}/versions/{V1_ID}", headers=dev_headers
    )
    assert r.status_code == 204
    assert [v["id"] for v in versions.rows] == [V2_ID]


def test_delete_active_version_is_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting the active (live) version is rejected with 400."""
    versions = _Table([_version(V1_ID)])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic(active_version_id=V1_ID)],
        topic_versions=versions,
    )
    _wire(monkeypatch, sb)

    r = client.delete(
        f"/v1/teacher/topics/{TOPIC_ID}/versions/{V1_ID}", headers=dev_headers
    )
    assert r.status_code == 400
    assert "active version" in r.json()["detail"]
    assert len(versions.rows) == 1


# ═══ POST /v1/teacher/topics/{id}/publish ═════════════════════════════════
def test_publish_succeeds_when_active_version_validated(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing a topic whose active version's `validation.passed` is True
    sets `status='published'`."""
    topics = _Table([_topic(active_version_id=V1_ID)])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=topics,
        topic_versions=[_version(V1_ID, validation=_PASS_VALIDATION)],
    )
    _wire(monkeypatch, sb)

    r = client.post(f"/v1/teacher/topics/{TOPIC_ID}/publish", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == {"id": TOPIC_ID, "status": "published"}
    assert topics.rows[0]["status"] == "published"


def test_publish_blocked_when_validation_failed(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing is blocked (400) when the active version failed validation."""
    topics = _Table([_topic(active_version_id=V1_ID)])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=topics,
        topic_versions=[_version(V1_ID, validation=_FAIL_VALIDATION)],
    )
    _wire(monkeypatch, sb)

    r = client.post(f"/v1/teacher/topics/{TOPIC_ID}/publish", headers=dev_headers)
    assert r.status_code == 400
    assert "has not validated" in r.json()["detail"]
    assert topics.rows[0]["status"] == "draft"


def test_publish_blocked_when_validation_missing(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing is blocked (400) when the active version has no
    `validation` (a version that was never validated)."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic(active_version_id=V1_ID)],
        topic_versions=[_version(V1_ID, validation=None)],
    )
    _wire(monkeypatch, sb)

    r = client.post(f"/v1/teacher/topics/{TOPIC_ID}/publish", headers=dev_headers)
    assert r.status_code == 400
    assert "has not validated" in r.json()["detail"]


def test_publish_blocked_when_no_active_version(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing a topic with no `active_version_id` is rejected (400)."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[_topic(active_version_id=None)],
    )
    _wire(monkeypatch, sb)

    r = client.post(f"/v1/teacher/topics/{TOPIC_ID}/publish", headers=dev_headers)
    assert r.status_code == 400
    assert "generate a lesson first" in r.json()["detail"]


def test_publish_non_owned_topic_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing a topic under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        topics=[_topic(active_version_id=V1_ID)],
    )
    _wire(monkeypatch, sb)

    r = client.post(f"/v1/teacher/topics/{TOPIC_ID}/publish", headers=dev_headers)
    assert r.status_code == 404


# ═══ GET /v1/teacher/units/{id} — now carries topics ══════════════════════
def test_get_unit_detail_includes_topics(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unit detail now lists the unit's `topics` ordered by `n`, each
    shaped `{id,n,name,status}`."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        topics=[
            _topic(),
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "unit_id": UNIT_ID,
                "n": 2,
                "name": "Acceleration",
                "status": "published",
            },
        ],
        pipeline_jobs=[],
        materials=[],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 200
    topics = r.json()["topics"]
    assert len(topics) == 2
    assert topics[0] == {"id": TOPIC_ID, "n": 1, "name": "Velocity", "status": "draft"}
    assert topics[1]["name"] == "Acceleration"
    assert topics[1]["status"] == "published"
