"""Async pipeline-job harness for the teacher-authoring feature.

The §6 pipeline stages (segment, generate) run for minutes — far past an
HTTP timeout — so they run as background jobs that advance a
`pipeline_jobs` row's `status` / `stage`. This package holds the generic,
idempotent, resumable *runner*; the real stage handlers are registered by
Phase 2.
"""

from __future__ import annotations

from app.pipeline.jobs import (
    STAGE_SEQUENCES,
    PipelineError,
    StageHandler,
    run_job,
)

__all__ = ["STAGE_SEQUENCES", "PipelineError", "StageHandler", "run_job"]
