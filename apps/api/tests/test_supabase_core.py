"""Tests for the ``app.core.supabase`` helper."""

from __future__ import annotations

import pytest

from app.core import supabase as supabase_core


def test_is_placeholder_url_local_loopback() -> None:
    assert supabase_core.is_placeholder_url("http://127.0.0.1:54321")
    assert supabase_core.is_placeholder_url("http://localhost:54321")
    assert not supabase_core.is_placeholder_url("https://proj.supabase.co")


def test_is_placeholder_url_empty() -> None:
    assert supabase_core.is_placeholder_url("")
    assert supabase_core.is_placeholder_url(None)


def test_supabase_enabled_off_in_dev_with_placeholder() -> None:
    # conftest sets DEV_MODE=true + placeholder URL — must be disabled.
    assert supabase_core.supabase_enabled() is False


def test_get_supabase_returns_none_when_disabled() -> None:
    assert supabase_core.get_supabase() is None


def test_supabase_enabled_true_for_real_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a real-looking URL and key, supabase_enabled() is True."""
    from app.core import config as config_module

    s = config_module.settings
    monkeypatch.setattr(s, "supabase_url", "https://realproject.supabase.co")
    # Force is_dev off by flipping both dev_mode + log_level.
    monkeypatch.setattr(s, "dev_mode", False)
    monkeypatch.setattr(s, "log_level", "INFO")
    assert supabase_core.supabase_enabled() is True
