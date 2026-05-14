"""Structured logging configuration via structlog.

In dev (LOG_LEVEL=DEBUG or ENVIRONMENT=development) we emit pretty,
colorized console output. In production we emit single-line JSON so that
log aggregators (Fly/Datadog/Logfire) can index it.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings


def configure_logging() -> None:
    """Configure both stdlib logging and structlog. Idempotent."""
    level = getattr(logging, settings.log_level, logging.INFO)

    # Tame uvicorn's loggers so they flow through structlog formatters.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_dev:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience wrapper around `structlog.get_logger`."""
    return structlog.get_logger(name) if name else structlog.get_logger()
