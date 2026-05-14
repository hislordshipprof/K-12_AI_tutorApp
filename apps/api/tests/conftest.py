"""Shared pytest fixtures.

These tests should run **without** any live secrets — Gemini and Supabase
clients are mocked. We also force `DEV_MODE=true` so the auth dependency
will accept `X-Dev-User-Id`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env BEFORE importing the app — pydantic-settings reads at import time.
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")


@pytest.fixture(scope="session")
def client() -> Iterator[Any]:
    """Synchronous TestClient — fine for FastAPI sync + async endpoints."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def dev_headers() -> dict[str, str]:
    """Headers that satisfy `get_current_user` in dev mode."""
    return {"X-Dev-User-Id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture
def mock_gemini_stream() -> AsyncMock:
    """AsyncMock for a stream_text result — yields three text fragments."""

    async def _gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
        for piece in ("Hello", " ", "world"):
            yield piece

    m = AsyncMock(side_effect=_gen)
    return m


@pytest.fixture
def mock_supabase() -> MagicMock:
    """Replace the supabase client factory with a MagicMock."""
    return MagicMock(name="supabase-client")
