"""Tests for the `pipeline_jobs` worker harness + poll endpoint (task 1.4).

Covers the four acceptance criteria from `docs/task-execution.md` 1.4:
  1. a queued fake multi-stage job runs every stage to `succeeded`;
  2. a job whose middle stage raises ends `failed` with `stage` preserved,
     and re-running RESUMES from that stage — earlier stages are NOT
     re-run (proven with a per-stage call counter) — and then succeeds;
  3. `GET /v1/teacher/jobs/{id}` reports the job's live `stage`;
  4. the endpoint 403s a non-teacher and 404s a teacher who does not own
     the job's course.

Supabase is mocked. The runner reads a job row, then repeatedly writes
and re-reads it, so the runner tests use a small stateful in-memory
`pipeline_jobs` fake rather than the one-shot builder mock used elsewhere.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.pipeline.jobs import PipelineError, run_job


# ─── stateful in-memory pipeline_jobs fake ────────────────────────────────
class _PipelineJobsTable:
    """A minimal stand-in for `supabase.table("pipeline_jobs")`.

    Holds one mutable job row in memory so `run_job`'s read -> update ->
    re-read cycle reflects each persisted stage, exactly like Postgres.
    Only the `.select()/.update()` chains the runner uses are modelled.
    """

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)
        self.history: list[str] = []  # every `stage` value the runner persisted

    # select chain --------------------------------------------------------
    def select(self, _columns: str = "*") -> "_PipelineJobsTable":
        self._mode = "select"
        return self

    def update(self, payload: dict[str, Any]) -> "_PipelineJobsTable":
        self._mode = "update"
        self._payload = payload
        return self

    def eq(self, _key: str, _value: Any) -> "_PipelineJobsTable":
        return self

    def limit(self, _n: int) -> "_PipelineJobsTable":
        return self

    def execute(self) -> MagicMock:
        if self._mode == "update":
            self.row.update(self._payload)
            if "stage" in self._payload:
                self.history.append(self._payload["stage"])
        return MagicMock(data=[dict(self.row)])


def _make_supabase(jobs: _PipelineJobsTable) -> MagicMock:
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: (
        jobs if name == "pipeline_jobs" else MagicMock(name=name)
    )
    return client


JOB_ID = "11111111-1111-1111-1111-111111111111"


# ═══ 1. queued job runs every stage to `succeeded` ════════════════════════
def test_queued_job_runs_all_stages_to_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued `generate` job walks rendering -> generating -> validating
    and finishes `succeeded` with no error."""
    jobs = _PipelineJobsTable(
        {
            "id": JOB_ID,
            "kind": "generate",
            "unit_id": None,
            "topic_id": "22222222-2222-2222-2222-222222222222",
            "status": "queued",
            "stage": None,
            "error": None,
        }
    )
    monkeypatch.setattr("app.pipeline.jobs.get_supabase", lambda: _make_supabase(jobs))

    ran: list[str] = []

    async def _stage_factory(name: str) -> Any:
        async def _h(_job: dict[str, Any]) -> None:
            ran.append(name)

        return _h

    handlers = {
        "rendering": asyncio.run(_stage_factory("rendering")),
        "generating": asyncio.run(_stage_factory("generating")),
        "validating": asyncio.run(_stage_factory("validating")),
    }

    final = asyncio.run(run_job(JOB_ID, handlers=handlers))

    assert final["status"] == "succeeded"
    assert final["error"] is None
    # Every stage ran exactly once, in order.
    assert ran == ["rendering", "generating", "validating"]
    # The runner persisted each stage as it advanced.
    assert jobs.history == ["rendering", "generating", "validating"]


# ═══ 2. fail mid-stage, then resume from that stage (no redo) ═════════════
def test_failed_job_resumes_from_failed_stage_without_redo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `segment` job whose `comprehending` stage raises ends `failed`
    with `stage='comprehending'`; re-running resumes at `comprehending`
    (NOT `converting`) and completes."""
    jobs = _PipelineJobsTable(
        {
            "id": JOB_ID,
            "kind": "segment",
            "unit_id": "33333333-3333-3333-3333-333333333333",
            "topic_id": None,
            "status": "queued",
            "stage": None,
            "error": None,
        }
    )
    monkeypatch.setattr("app.pipeline.jobs.get_supabase", lambda: _make_supabase(jobs))

    # Per-stage call counters prove `converting` is NOT re-run on retry.
    calls = {"converting": 0, "comprehending": 0}
    fail_once = {"comprehending": True}

    async def _converting(_job: dict[str, Any]) -> None:
        calls["converting"] += 1

    async def _comprehending(_job: dict[str, Any]) -> None:
        calls["comprehending"] += 1
        if fail_once["comprehending"]:
            fail_once["comprehending"] = False
            raise RuntimeError("comprehension model timed out")

    handlers = {"converting": _converting, "comprehending": _comprehending}

    # First run: converting succeeds, comprehending raises.
    first = asyncio.run(run_job(JOB_ID, handlers=handlers))
    assert first["status"] == "failed"
    assert first["stage"] == "comprehending"  # failed stage preserved
    assert first["error"] == "comprehension model timed out"
    assert calls == {"converting": 1, "comprehending": 1}

    # Re-run the failed job: it must resume AT comprehending — converting
    # already completed and must not run again.
    second = asyncio.run(run_job(JOB_ID, handlers=handlers))
    assert second["status"] == "succeeded"
    assert second["error"] is None
    # `converting` ran ONCE total (first run only); `comprehending` ran twice.
    assert calls == {"converting": 1, "comprehending": 2}


def test_rerunning_succeeded_job_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running an already-`succeeded` job does not re-run any stage."""
    jobs = _PipelineJobsTable(
        {
            "id": JOB_ID,
            "kind": "segment",
            "unit_id": "33333333-3333-3333-3333-333333333333",
            "topic_id": None,
            "status": "succeeded",
            "stage": "comprehending",
            "error": None,
        }
    )
    monkeypatch.setattr("app.pipeline.jobs.get_supabase", lambda: _make_supabase(jobs))

    ran: list[str] = []

    async def _h(_job: dict[str, Any]) -> None:
        ran.append("x")

    final = asyncio.run(
        run_job(JOB_ID, handlers={"converting": _h, "comprehending": _h})
    )
    assert final["status"] == "succeeded"
    assert ran == []  # no stage executed
    assert jobs.history == []  # nothing persisted


def test_run_job_unknown_kind_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job with an unrecognised `kind` is a hard error, not a silent pass."""
    jobs = _PipelineJobsTable(
        {
            "id": JOB_ID,
            "kind": "bogus",
            "unit_id": None,
            "topic_id": None,
            "status": "queued",
            "stage": None,
            "error": None,
        }
    )
    monkeypatch.setattr("app.pipeline.jobs.get_supabase", lambda: _make_supabase(jobs))

    with pytest.raises(PipelineError):
        asyncio.run(run_job(JOB_ID, handlers={}))


# ═══ endpoint mock plumbing ───────────────────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


def _profiles_role(role: str) -> MagicMock:
    return _select_chain([{"role": role}])


TEACHER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TEACHER_ID = "00000000-0000-0000-0000-0000000000ff"
UNIT_ID = "33333333-3333-3333-3333-333333333333"
COURSE_ID = "44444444-4444-4444-4444-444444444444"


def _endpoint_supabase(
    *,
    job_row: dict[str, Any] | None,
    owner_id: str | None,
    role: str,
) -> MagicMock:
    """Supabase mock for the GET endpoint — dispatches per table.

    `pipeline_jobs` -> the job row (or none); `units`/`courses` -> the
    ownership chain; `profiles` -> the caller's role.
    """
    tables: dict[str, MagicMock] = {
        "pipeline_jobs": _select_chain([job_row] if job_row else []),
        "profiles": _profiles_role(role),
        "units": _select_chain(
            [{"id": UNIT_ID, "course_id": COURSE_ID}] if owner_id is not None else []
        ),
        "courses": _select_chain(
            [{"id": COURSE_ID, "owner_id": owner_id}] if owner_id is not None else []
        ),
        "topics": _select_chain([{"id": "t", "unit_id": UNIT_ID}]),
    }
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: tables[name]
    return client


# ═══ 3. endpoint reports the live `stage` ═════════════════════════════════
def test_get_job_reports_live_stage(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /v1/teacher/jobs/{id}` returns the job's current status + stage."""
    job_row = {
        "id": JOB_ID,
        "kind": "segment",
        "unit_id": UNIT_ID,
        "topic_id": None,
        "status": "running",
        "stage": "comprehending",
        "error": None,
    }
    sb = _endpoint_supabase(job_row=job_row, owner_id=TEACHER_ID, role="teacher")
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)

    r = client.get(f"/v1/teacher/jobs/{JOB_ID}", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["stage"] == "comprehending"
    assert body["kind"] == "segment"


def test_get_job_admin_can_read_any_job(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin reads a job they do not own — no ownership check applies."""
    job_row = {
        "id": JOB_ID,
        "kind": "segment",
        "unit_id": UNIT_ID,
        "topic_id": None,
        "status": "succeeded",
        "stage": "comprehending",
        "error": None,
    }
    # Course is owned by some OTHER teacher; caller is an admin.
    sb = _endpoint_supabase(job_row=job_row, owner_id=OTHER_TEACHER_ID, role="admin")
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)

    r = client.get(f"/v1/teacher/jobs/{JOB_ID}", headers=dev_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"


def test_get_job_missing_is_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown job id 404s."""
    sb = _endpoint_supabase(job_row=None, owner_id=TEACHER_ID, role="teacher")
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)

    r = client.get(f"/v1/teacher/jobs/{JOB_ID}", headers=dev_headers)
    assert r.status_code == 404


# ═══ 4. endpoint 403s the wrong role / 404s a non-owner ═══════════════════
def test_get_job_non_teacher_gets_403(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller is forbidden from the teacher route."""
    sb = _endpoint_supabase(job_row=None, owner_id=None, role="student")
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)

    r = client.get(f"/v1/teacher/jobs/{JOB_ID}", headers=dev_headers)
    assert r.status_code == 403


def test_get_job_non_owner_teacher_gets_404(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher who does not own the job's course gets 404 (not 403, so the
    endpoint does not leak that the job exists)."""
    job_row = {
        "id": JOB_ID,
        "kind": "segment",
        "unit_id": UNIT_ID,
        "topic_id": None,
        "status": "running",
        "stage": "converting",
        "error": None,
    }
    # The course is owned by a DIFFERENT teacher; the caller is a teacher.
    sb = _endpoint_supabase(job_row=job_row, owner_id=OTHER_TEACHER_ID, role="teacher")
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.teacher.get_supabase", lambda: sb)

    r = client.get(f"/v1/teacher/jobs/{JOB_ID}", headers=dev_headers)
    assert r.status_code == 404
