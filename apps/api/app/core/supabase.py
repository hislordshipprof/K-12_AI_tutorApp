"""Backend Supabase client helper.

Thin wrapper around ``app.services.supabase`` that adds:

- A single ``get_supabase()`` entrypoint suitable as a FastAPI dependency.
- A ``supabase_enabled()`` predicate that the API routers use to decide
  whether to fall through to local sample/stub data (DEV_MODE).
- A ``is_placeholder_url()`` helper so we can keep the local-dev story
  working even with the placeholder ``http://127.0.0.1:54321`` URL.

The endpoint modules import from here rather than from ``app.services``
so the indirection is easy to mock in tests (one symbol to patch).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


_PLACEHOLDER_HOSTS = ("127.0.0.1:54321", "localhost:54321")


def is_placeholder_url(url: str | None = None) -> bool:
    """True when SUPABASE_URL points at the unconfigured local placeholder."""
    target = url if url is not None else settings.supabase_url
    if not target:
        return True
    return any(host in target for host in _PLACEHOLDER_HOSTS)


def supabase_enabled() -> bool:
    """True when we should attempt real Supabase queries.

    False when:
      * No URL / service-role key is configured.
      * URL is the local placeholder AND we're in DEV_MODE
        (so local dev without `supabase start` keeps working).
    """
    if not settings.supabase_url:
        return False
    if not settings.supabase_service_role_key.get_secret_value():
        return False
    if settings.is_dev and is_placeholder_url():
        return False
    return True


def get_supabase() -> Any | None:
    """Return the cached service-role client, or ``None`` when disabled.

    Returns None in two cases (both fine for callers — they should fall
    back to sample data or 503 as appropriate):
      1. ``supabase_enabled()`` is False (config / dev placeholder).
      2. The client factory itself raises (e.g. supabase package missing).
    """
    if not supabase_enabled():
        return None
    try:
        from app.services.supabase import get_supabase_admin

        return get_supabase_admin()
    except Exception as e:  # noqa: BLE001
        log.warning("supabase_client_init_failed", error=str(e))
        return None


__all__ = ["get_supabase", "supabase_enabled", "is_placeholder_url"]
