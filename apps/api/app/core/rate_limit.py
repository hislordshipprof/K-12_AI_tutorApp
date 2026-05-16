"""Per-user rate limiting + voice-WS concurrency gate.

Two layers:

1. `limiter` — `slowapi.Limiter` keyed by user (JWT sub / X-Dev-User-Id / IP).
   Applied to expensive endpoints via the `@limiter.limit("N/minute")`
   decorator. Routes that use this decorator MUST declare `request: Request`
   in their signature — slowapi inspects it.

2. `voice_acquire` / `voice_release` — asyncio-safe counter that gates
   simultaneous Gemini Live WebSocket sessions to one per user. Cheap
   protection against an attacker opening many WS connections under a
   single account to multiply Gemini cost.

This module is intentionally in-process / single-instance. If we scale the
API to multiple Fly machines, swap the storage URI to Redis (slowapi
supports `redis://...` out of the box) and replace the voice counter with
a Redis SETNX or a per-instance hard cap behind a load balancer.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _user_key(request: Request) -> str:
    """Pick the most specific identity available, falling back to IP."""
    dev = request.headers.get("X-Dev-User-Id")
    if dev:
        return f"dev:{dev}"
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        # Hash a fixed-length prefix of the bearer token. Token is per-user;
        # using a prefix avoids storing/exposing the whole JWT in the
        # limiter's keyspace. 32 chars is enough entropy for a key.
        return f"jwt:{auth[7:39]}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_user_key, headers_enabled=True)


# ── Voice WS concurrency gate ────────────────────────────────────────────────
MAX_VOICE_PER_USER = 1

_voice_active: dict[str, int] = defaultdict(int)
_voice_lock = asyncio.Lock()


async def voice_acquire(user_id: str) -> bool:
    """Try to reserve a voice session slot. Returns False when over the cap."""
    async with _voice_lock:
        if _voice_active[user_id] >= MAX_VOICE_PER_USER:
            return False
        _voice_active[user_id] += 1
        return True


async def voice_release(user_id: str) -> None:
    """Release the slot held by `voice_acquire`. Safe to call on errors."""
    async with _voice_lock:
        if _voice_active[user_id] > 0:
            _voice_active[user_id] -= 1
        if _voice_active[user_id] == 0:
            # Keep the dict bounded — drop empty entries.
            _voice_active.pop(user_id, None)


# ── Teacher ingest rate-limit + daily quota (teacher-authoring.md §6) ────────
# Uploads (and segment/generate calls) trigger expensive multimodal/Pro work.
# `ingest_acquire` is an asyncio-safe sliding-window gate per teacher: a
# short-window rate limit AND a rolling 24h quota. Same in-process caveat as
# the voice counter above — swap to Redis when the API scales out.
_ingest_events: dict[str, deque[float]] = defaultdict(deque)
_ingest_lock = asyncio.Lock()

_WINDOW_S = 60.0
_DAY_S = 86_400.0


class RateLimitExceeded(RuntimeError):
    """Raised when a teacher exceeds the ingest rate limit or daily quota."""


async def ingest_acquire(teacher_id: str) -> None:
    """Record one ingest call for `teacher_id`, or raise `RateLimitExceeded`.

    Enforces two limits from a single per-teacher timestamp log:
      * no more than `ingest_rate_per_minute` calls in any 60s window;
      * no more than `ingest_quota_per_day` calls in any rolling 24h window.

    A rejected call is NOT recorded, so a teacher who hits the limit and
    backs off recovers cleanly once the window slides.
    """
    now = time.monotonic()
    async with _ingest_lock:
        events = _ingest_events[teacher_id]
        # Drop anything older than the longest window we care about.
        while events and now - events[0] > _DAY_S:
            events.popleft()
        in_minute = sum(1 for t in events if now - t <= _WINDOW_S)
        if in_minute >= settings.ingest_rate_per_minute:
            raise RateLimitExceeded(
                f"ingest rate limit: {settings.ingest_rate_per_minute}/min exceeded"
            )
        if len(events) >= settings.ingest_quota_per_day:
            raise RateLimitExceeded(
                f"ingest daily quota: {settings.ingest_quota_per_day}/day exceeded"
            )
        events.append(now)


__all__ = [
    "limiter",
    "voice_acquire",
    "voice_release",
    "MAX_VOICE_PER_USER",
    "ingest_acquire",
    "RateLimitExceeded",
]
