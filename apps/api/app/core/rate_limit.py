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
from collections import defaultdict

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


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


__all__ = ["limiter", "voice_acquire", "voice_release", "MAX_VOICE_PER_USER"]
