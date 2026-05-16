"""Tests for the segmentation-pipeline endpoints (task 3.4).

Wires the Phase 2 segmentation/confirm service layer into HTTP
(`teacher-authoring.md` §6/§10/§13):

  * `POST /v1/teacher/units/{id}/segment` — enqueues a `segment`
    `pipeline_jobs` row and runs it in the background; rejects a unit with
    no material / a still-converting material (400); returns an existing
    in-flight job instead of starting a second (§13); non-owned unit 404s;
    a non-teacher is 403'd.
  * `GET /v1/teacher/units/{id}/segmentation` — the latest proposed
    breakdown (`topics` + `teach=false` `excluded` pages + `materials`);
    404 with no segmentation row; non-owned unit 404s.
  * `POST /v1/teacher/units/{id}/topics` — writes the edited breakdown onto
    the segmentation row and calls `confirm_breakdown`; a malformed topic
    422s; non-owned unit / no-segmentation 404.
  * `GET /v1/teacher/units/{id}` — now also carries `segment_job`.

Supabase is mocked with the same per-table builder / stateful `_Table`
fake as `test_course_management.py`. `run_job` and `confirm_breakdown` are
patched so no background work touches Gemini or a real DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipeline.confirm import ConfirmError, ConfirmResult

# `dev_headers` authenticates as this id (see conftest.py).
TEACHER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TEACHER_ID = "00000000-0000-0000-0000-0000000000ff"
COURSE_ID = "11111111-1111-1111-1111-111111111111"
UNIT_ID = "22222222-2222-2222-2222-222222222222"
MATERIAL_ID = "44444444-4444-4444-4444-444444444444"
SEG_ID = "55555555-5555-5555-5555-555555555555"
JOB_ID = "66666666-6666-6666-6666-666666666666"


# ─── select-chain mock (read-only tables) ─────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A MagicMock that mimics a Supabase select builder chain."""
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "in_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


# ─── stateful generic table fake (mirrors test_course_management._Table) ──
class _Table:
    """A minimal stateful stand-in for a Supabase table.

    Models select / insert / update chains against an in-memory list, with
    `.eq()` / `.in_()` filters applied on execute, so a read after a write
    reflects the change. An optional `id_for` hook assigns ids to inserts.
    """

    def __init__(self, rows: list[dict[str, Any]], *, id_for: Any = None) -> None:
        self.rows = [dict(r) for r in rows]
        self._id_for = id_for

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
    courses: list[dict[str, Any]] | None = None,
    units: list[dict[str, Any]] | None = None,
    materials: list[dict[str, Any]] | None = None,
    pipeline_jobs: _Table | list[dict[str, Any]] | None = None,
    unit_segmentations: _Table | list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock dispatching each table name to its builder."""
    jobs_tbl = (
        pipeline_jobs
        if isinstance(pipeline_jobs, _Table)
        else _Table(pipeline_jobs or [])
    )
    seg_tbl = (
        unit_segmentations
        if isinstance(unit_segmentations, _Table)
        else _Table(unit_segmentations or [])
    )
    chains: dict[str, Any] = {
        "courses": _Table(courses or []),
        "units": _Table(units or []),
        "lesson_materials": _Table(materials or []),
        "pipeline_jobs": jobs_tbl,
        "unit_segmentations": seg_tbl,
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


# ═══ POST /v1/teacher/units/{id}/segment ══════════════════════════════════
def test_segment_enqueues_job_and_returns_job_id(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit with converted materials gets a queued `segment` job row and a
    `job_id` back; the background `run_job` is a patched no-op."""
    jobs = _Table([])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[
            {"id": MATERIAL_ID, "unit_id": UNIT_ID, "conversion_status": "converted"}
        ],
        pipeline_jobs=jobs,
    )
    _wire(monkeypatch, sb)
    run_job_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.teacher.run_job", run_job_mock)

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["status"] == "queued"

    assert len(jobs.rows) == 1
    row = jobs.rows[0]
    assert row["kind"] == "segment"
    assert row["unit_id"] == UNIT_ID
    assert row["status"] == "queued"
    assert row["stage"] is None
    assert row["id"] == body["job_id"]


def test_segment_no_materials_is_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit with no material cannot be segmented (400)."""
    sb = _make_supabase(
        role="teacher", courses=_owned_course(), units=_unit(), materials=[]
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 400
    assert "no material" in r.json()["detail"]


def test_segment_unconverted_material_is_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A still-converting material blocks segmentation (400, §13)."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[
            {"id": "m1", "unit_id": UNIT_ID, "conversion_status": "converted"},
            {"id": "m2", "unit_id": UNIT_ID, "conversion_status": "pending"},
        ],
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 400
    assert "still converting" in r.json()["detail"]


def test_segment_returns_inflight_job_without_inserting(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `running` segment job already exists -> it is returned and NO new
    `pipeline_jobs` row is inserted (§13 — one in-flight per unit)."""
    jobs = _Table(
        [
            {
                "id": JOB_ID,
                "kind": "segment",
                "unit_id": UNIT_ID,
                "status": "running",
                "stage": "comprehending",
            }
        ]
    )
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[
            {"id": MATERIAL_ID, "unit_id": UNIT_ID, "conversion_status": "converted"}
        ],
        pipeline_jobs=jobs,
    )
    _wire(monkeypatch, sb)
    run_job_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.teacher.run_job", run_job_mock)

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"] == JOB_ID
    assert body["status"] == "running"
    # No second job inserted.
    assert len(jobs.rows) == 1


def test_segment_non_owned_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segmenting a unit under another teacher's course 404s."""
    sb = _make_supabase(role="teacher", courses=_other_course(), units=_unit())
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 404


def test_segment_non_teacher_is_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller cannot enqueue a segment job."""
    sb = _make_supabase(role="student")
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.run_job", AsyncMock())

    r = client.post(f"/v1/teacher/units/{UNIT_ID}/segment", headers=dev_headers)
    assert r.status_code == 403


# ═══ GET /v1/teacher/units/{id}/segmentation ══════════════════════════════
def _segmentation_row() -> dict[str, Any]:
    return {
        "id": SEG_ID,
        "unit_id": UNIT_ID,
        "status": "proposed",
        "comprehension": {
            "pages": [
                {"material_idx": 0, "page_idx": 0, "teach": False, "reason": "title"},
                {"material_idx": 0, "page_idx": 1, "teach": True, "reason": ""},
                {
                    "material_idx": 0,
                    "page_idx": 9,
                    "teach": False,
                    "reason": "agenda",
                },
            ]
        },
        "proposed": {
            "topics": [
                {
                    "title": "Velocity",
                    "summary": "What velocity is.",
                    "key_points": ["speed has direction"],
                    "pages": [{"material_idx": 0, "page_idx": 1}],
                }
            ],
            "practice_tags": [],
            "empty_reason": None,
        },
    }


def test_get_segmentation_returns_topics_excluded_materials(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The latest proposed breakdown comes back with `topics`, the
    `teach=false` `excluded` pages only, and the unit's `materials`."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[
            {"id": MATERIAL_ID, "unit_id": UNIT_ID, "filename": "deck.pdf"}
        ],
        unit_segmentations=[_segmentation_row()],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}/segmentation", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "proposed"
    assert len(body["topics"]) == 1
    assert body["topics"][0]["title"] == "Velocity"
    # Only the two teach=false pages are excluded; the teach=true one is not.
    assert len(body["excluded"]) == 2
    reasons = {e["reason"] for e in body["excluded"]}
    assert reasons == {"title", "agenda"}
    assert body["materials"] == [{"idx": 0, "filename": "deck.pdf"}]
    assert body["empty_reason"] is None


def test_get_segmentation_no_row_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit with no `unit_segmentations` row 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        unit_segmentations=[],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}/segmentation", headers=dev_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "no segmentation"


def test_get_segmentation_non_owned_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit under another teacher's course 404s before any seg lookup."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        unit_segmentations=[_segmentation_row()],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}/segmentation", headers=dev_headers)
    assert r.status_code == 404


# ═══ POST /v1/teacher/units/{id}/topics ═══════════════════════════════════
_VALID_TOPIC = {
    "title": "Velocity",
    "summary": "Velocity is speed with a direction.",
    "key_points": ["speed has direction"],
    "pages": [{"material_idx": 0, "page_idx": 1}],
}


def test_confirm_topics_updates_row_and_calls_confirm_breakdown(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid `{topics:[...]}` body writes the edited breakdown onto the
    segmentation row (`status='confirmed'`) and calls `confirm_breakdown`;
    the response carries `topic_ids` / `created` / `page_count`."""
    seg = _Table([_segmentation_row()])
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        unit_segmentations=seg,
    )
    _wire(monkeypatch, sb)

    confirm_mock = AsyncMock(
        return_value=ConfirmResult(
            unit_id=UNIT_ID,
            segmentation_id=SEG_ID,
            topic_ids=["t1"],
            created=1,
            updated=0,
            page_count=1,
        )
    )
    monkeypatch.setattr("app.api.v1.teacher.confirm_breakdown", confirm_mock)

    edited = {**_VALID_TOPIC, "title": "Velocity (edited)"}
    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/topics",
        headers=dev_headers,
        json={"topics": [edited]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["topic_ids"] == ["t1"]
    assert body["created"] == 1
    assert body["updated"] == 0
    assert body["page_count"] == 1

    # The segmentation row was updated with the edited topics + confirmed.
    row = seg.rows[0]
    assert row["status"] == "confirmed"
    assert row["proposed"]["topics"][0]["title"] == "Velocity (edited)"
    # Pre-existing proposed fields (practice_tags) are preserved.
    assert "practice_tags" in row["proposed"]
    confirm_mock.assert_awaited_once_with(UNIT_ID)


def test_confirm_topics_malformed_topic_is_422(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A topic missing the required `summary` field fails validation (422)."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        unit_segmentations=[_segmentation_row()],
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.confirm_breakdown", AsyncMock())

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/topics",
        headers=dev_headers,
        json={"topics": [{"title": "No summary"}]},
    )
    assert r.status_code == 422


def test_confirm_topics_no_segmentation_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming with no `unit_segmentations` row 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        unit_segmentations=[],
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.confirm_breakdown", AsyncMock())

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/topics",
        headers=dev_headers,
        json={"topics": [_VALID_TOPIC]},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "no segmentation"


def test_confirm_topics_non_owned_unit_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming a unit under another teacher's course 404s."""
    sb = _make_supabase(
        role="teacher",
        courses=_other_course(),
        units=_unit(),
        unit_segmentations=[_segmentation_row()],
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr("app.api.v1.teacher.confirm_breakdown", AsyncMock())

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/topics",
        headers=dev_headers,
        json={"topics": [_VALID_TOPIC]},
    )
    assert r.status_code == 404


def test_confirm_topics_confirm_error_is_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `ConfirmError` from `confirm_breakdown` surfaces as a 400."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        unit_segmentations=_Table([_segmentation_row()]),
    )
    _wire(monkeypatch, sb)
    monkeypatch.setattr(
        "app.api.v1.teacher.confirm_breakdown",
        AsyncMock(side_effect=ConfirmError("empty_breakdown", "nothing to confirm")),
    )

    r = client.post(
        f"/v1/teacher/units/{UNIT_ID}/topics",
        headers=dev_headers,
        json={"topics": [_VALID_TOPIC]},
    )
    assert r.status_code == 400
    assert "nothing to confirm" in r.json()["detail"]


# ═══ GET /v1/teacher/units/{id} — now carries segment_job ═════════════════
def test_get_unit_detail_segment_job_null_when_none(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit that has never been segmented reports `segment_job: null`."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[
            {
                "id": MATERIAL_ID,
                "unit_id": UNIT_ID,
                "filename": "deck.pdf",
                "kind": None,
                "conversion_status": "converted",
            }
        ],
        pipeline_jobs=[],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 200
    assert r.json()["segment_job"] is None


def test_get_unit_detail_includes_latest_segment_job(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit with a segment job reports it shaped `{id,status,stage}`."""
    sb = _make_supabase(
        role="teacher",
        courses=_owned_course(),
        units=_unit(),
        materials=[],
        pipeline_jobs=[
            {
                "id": JOB_ID,
                "kind": "segment",
                "unit_id": UNIT_ID,
                "status": "running",
                "stage": "comprehending",
            }
        ],
    )
    _wire(monkeypatch, sb)

    r = client.get(f"/v1/teacher/units/{UNIT_ID}", headers=dev_headers)
    assert r.status_code == 200
    job = r.json()["segment_job"]
    assert job == {"id": JOB_ID, "status": "running", "stage": "comprehending"}
