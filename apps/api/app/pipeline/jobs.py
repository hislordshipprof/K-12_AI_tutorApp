"""Pipeline-job runner — the async, idempotent, resumable worker harness.

`teacher-authoring.md` §6 principle 4: the segment + generate pipeline
stages take minutes, so they run as background jobs against a
`pipeline_jobs` row. This module is the generic *runner* — it does NOT
know how to convert a document or generate a lesson; it only knows how to
walk a job's fixed stage sequence, persist progress after every stage,
and resume from the failed stage on a re-run.

Stage sequences (`teacher-authoring.md` §4) are FIXED:
  * ``segment``  job:  ``converting`` -> ``comprehending``
  * ``generate`` job:  ``rendering`` -> ``generating`` -> ``validating``

The real stage *handlers* are Phase 2 — `STAGE_HANDLERS` ships empty and
Phase 2 registers the real implementations. For Phase 1.4 a stage with no
registered handler is a no-op (the harness still advances `status`/`stage`
so it is fully exercisable, and the acceptance test injects fake handlers
to prove resume-from-failure).

Resumability (§13 "Pipeline crashes mid-run"): every stage persists
`stage` + `status='running'` *before* it runs. A job that failed at
`comprehending` is re-run starting at `comprehending` — earlier stages
that already completed are skipped, because the runner resumes at the
job's persisted `stage`. Re-running a `succeeded` job is a no-op.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.core.supabase import get_supabase

log = get_logger(__name__)

# ── Fixed stage sequences (teacher-authoring.md §4) ──────────────────────────
STAGE_SEQUENCES: dict[str, tuple[str, ...]] = {
    "segment": ("converting", "comprehending"),
    "generate": ("rendering", "generating", "validating"),
}

# A stage handler is an async callable given the job row; its return value
# is ignored. Phase 2 registers the real handlers here. An unregistered
# stage is treated as a no-op (Phase 1.4 harness has no real stage logic).
StageHandler = Callable[[dict[str, Any]], Awaitable[None]]
STAGE_HANDLERS: dict[str, StageHandler] = {}


class PipelineError(RuntimeError):
    """Raised inside the runner when a job row cannot be advanced."""


async def _noop_stage(_job: dict[str, Any]) -> None:
    """Default handler for a stage with nothing registered (Phase 1.4)."""
    return None


def _persist(
    supabase: Any,
    job_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Write `fields` onto the job row and return the updated row.

    `updated_at` is bumped on every write so a poller can see liveness.
    """
    payload = {**fields, "updated_at": "now()"}
    resp = (
        supabase.table("pipeline_jobs")
        .update(payload)
        .eq("id", job_id)
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        raise PipelineError(f"pipeline_jobs row {job_id} vanished mid-run")
    return rows[0]


async def run_job(
    job_id: str,
    *,
    handlers: dict[str, StageHandler] | None = None,
) -> dict[str, Any]:
    """Run the `pipeline_jobs` row `job_id` through its stage sequence.

    The runner is idempotent and resumable:

    * A ``queued`` job runs every stage of its kind, in order.
    * A ``failed`` job resumes AT its persisted ``stage`` — the stages
      before it already completed and are NOT re-run.
    * A ``succeeded`` job is a no-op (returned unchanged).
    * A ``running`` job is resumed from its persisted ``stage`` too — a
      crash leaves a row ``running`` and a re-run picks it back up.

    Before each stage the runner persists ``stage`` + ``status='running'``
    so a crash-then-rerun knows exactly where to resume. On a stage
    exception it persists ``status='failed'`` + ``error`` and leaves
    ``stage`` at the failing stage. On the last stage it persists
    ``status='succeeded'`` + ``error=null``.

    Args:
        job_id: the `pipeline_jobs.id` to run.
        handlers: stage-name -> async handler. Defaults to the module
            `STAGE_HANDLERS` registry; tests inject fakes here.

    Returns:
        The final `pipeline_jobs` row.
    """
    registry = STAGE_HANDLERS if handlers is None else handlers

    supabase = get_supabase()
    if supabase is None:
        # No DB wired (local-dev placeholder). The runner needs a row to
        # advance; report honestly rather than pretending success.
        raise PipelineError("pipeline runner requires Supabase to be configured")

    # 1. Load the job row.
    resp = (
        supabase.table("pipeline_jobs")
        .select("id,kind,unit_id,topic_id,status,stage,error")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        raise PipelineError(f"pipeline_jobs row {job_id} not found")
    job: dict[str, Any] = rows[0]

    kind = str(job.get("kind") or "")
    sequence = STAGE_SEQUENCES.get(kind)
    if sequence is None:
        raise PipelineError(f"unknown pipeline job kind: {kind!r}")

    # 2. Already-finished job → no-op (idempotent re-run).
    if job.get("status") == "succeeded":
        log.info("pipeline_job_already_succeeded", job_id=job_id)
        return job

    # 3. Decide where to start. A queued job starts at stage 0; a failed or
    #    running job RESUMES at its persisted stage — earlier stages already
    #    completed, so we never re-do them.
    start = 0
    persisted_stage = job.get("stage")
    if job.get("status") in ("failed", "running") and persisted_stage in sequence:
        start = sequence.index(persisted_stage)
        log.info(
            "pipeline_job_resume",
            job_id=job_id,
            from_stage=persisted_stage,
            skipped=list(sequence[:start]),
        )

    # 4. Walk the stages from `start` to the end.
    for stage in sequence[start:]:
        # Persist progress BEFORE running the stage, so a crash mid-stage
        # leaves the row pointing at exactly this stage to resume from.
        job = _persist(supabase, job_id, {"status": "running", "stage": stage})
        handler = registry.get(stage, _noop_stage)
        try:
            await handler(job)
        except Exception as e:  # noqa: BLE001 — any stage failure is recorded
            log.warning("pipeline_stage_failed", job_id=job_id, stage=stage, error=str(e))
            job = _persist(
                supabase,
                job_id,
                {"status": "failed", "stage": stage, "error": str(e)},
            )
            return job

    # 5. Every stage passed — mark the job succeeded.
    job = _persist(supabase, job_id, {"status": "succeeded", "error": None})
    log.info("pipeline_job_succeeded", job_id=job_id, kind=kind)
    return job
