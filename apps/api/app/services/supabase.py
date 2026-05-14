"""Supabase client factories.

Two clients are exposed:

- `get_supabase_anon()` — anon key. Use for operations that respect Row
  Level Security on behalf of the *requesting user*. Inject the user's
  JWT before each request via `client.postgrest.auth(jwt)`.
- `get_supabase_admin()` — service_role key. **Server-side only**;
  bypasses RLS. Use sparingly (admin tasks, agent traces, etc).

Clients are memoized as module-level singletons.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _build_client(key: str) -> Any:
    """Construct a Supabase client. Imported lazily so unit tests don't
    require the supabase library to be installed at collection time."""
    from supabase import Client, create_client  # type: ignore[import-not-found]

    if not settings.supabase_url or not key:
        raise RuntimeError(
            "Supabase credentials are not configured (SUPABASE_URL / key missing)."
        )
    client: Client = create_client(settings.supabase_url, key)
    return client


@lru_cache(maxsize=1)
def get_supabase_anon() -> Any:
    """Cached anon-key client. Per-request user JWT must be attached separately."""
    return _build_client(settings.supabase_anon_key.get_secret_value())


@lru_cache(maxsize=1)
def get_supabase_admin() -> Any:
    """Cached service_role client. Bypasses RLS — server-side use only."""
    return _build_client(settings.supabase_service_role_key.get_secret_value())
