"""Tests for the §14 compliance baseline (task 0.4).

Covers two pieces of the compliance baseline:

  1. `DELETE /v1/me` — self-service account deletion. It must require
     authentication and may delete ONLY the calling user's own account
     (the target is taken from the verified JWT, never from the request).
  2. Terms-acceptance recording — the `20260515040000_terms_acceptance.sql`
     migration adds `profiles.terms_accepted_at` and extends the
     `handle_new_user` trigger to copy it from sign-up metadata. The trigger
     itself runs in Postgres (not pytest-reachable), so we assert the
     migration's idempotent shape and that it wires the column.

Supabase is mocked — the deletion endpoint goes through `get_supabase`
and calls the admin auth API (`supabase.auth.admin.delete_user`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

CALLER_ID = "00000000-0000-0000-0000-000000000001"


# ─── DELETE /v1/me — account deletion ─────────────────────────────────────
def _supabase_with_admin() -> MagicMock:
    """A supabase mock exposing `.auth.admin.delete_user(...)`."""
    sb = MagicMock(name="supabase")
    sb.auth.admin.delete_user = MagicMock(name="delete_user")
    return sb


def test_delete_me_requires_auth(client: Any) -> None:
    """`DELETE /v1/me` with no credentials is rejected (401)."""
    r = client.delete("/v1/me")
    assert r.status_code == 401


def test_delete_me_deletes_the_caller(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signed-in user deletes their own account → 204, and the admin
    delete is called with *their own* id (taken from the JWT/claims)."""
    sb = _supabase_with_admin()
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.delete("/v1/me", headers=dev_headers)
    assert r.status_code == 204

    # The auth.users row deleted is the caller's — never anyone else's.
    sb.auth.admin.delete_user.assert_called_once_with(CALLER_ID)


def test_delete_me_uses_only_the_jwt_subject(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deletion target comes from the authenticated identity only.

    The endpoint takes no body/path/query for a target user, so a caller
    cannot point it at someone else. Whatever id authenticates is the id
    deleted — proven here by authenticating as a different user.
    """
    other_id = "11111111-1111-1111-1111-111111111111"
    sb = _supabase_with_admin()
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.delete("/v1/me", headers={"X-Dev-User-Id": other_id})
    assert r.status_code == 204
    sb.auth.admin.delete_user.assert_called_once_with(other_id)


def test_delete_me_503_when_supabase_unavailable(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no Supabase backing store, deletion reports 503 honestly
    rather than pretending the account was removed."""
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: None)

    r = client.delete("/v1/me", headers=dev_headers)
    assert r.status_code == 503


def test_delete_me_503_when_admin_delete_raises(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the admin delete call fails, the endpoint surfaces a 503 — it
    does not return a misleading success."""
    sb = _supabase_with_admin()
    sb.auth.admin.delete_user.side_effect = RuntimeError("network down")
    monkeypatch.setattr("app.api.v1.me.get_supabase", lambda: sb)

    r = client.delete("/v1/me", headers=dev_headers)
    assert r.status_code == 503


# ─── Terms-acceptance recording — migration guard ─────────────────────────
def _terms_migration_sql() -> str:
    """Read the task-0.4 terms-acceptance migration."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # apps/api/tests/ -> repo root
    path = (
        repo_root
        / "supabase"
        / "migrations"
        / "20260515040000_terms_acceptance.sql"
    )
    assert path.exists(), f"terms-acceptance migration missing: {path}"
    return path.read_text(encoding="utf-8")


def test_terms_migration_adds_column_idempotently() -> None:
    """The migration adds `profiles.terms_accepted_at` with `if not exists`
    so it is safe to re-run (CLAUDE.md "Definition of done")."""
    sql = _terms_migration_sql().lower()
    assert "terms_accepted_at" in sql
    assert "add column if not exists terms_accepted_at" in sql


def test_terms_migration_wires_handle_new_user_trigger() -> None:
    """The migration re-defines `handle_new_user` so sign-up metadata's
    `terms_accepted_at` lands on the new profiles row — i.e. terms
    acceptance is recorded at sign-up."""
    sql = _terms_migration_sql().lower()
    assert "create or replace function public.handle_new_user" in sql
    # the trigger reads the value out of the sign-up metadata
    assert "raw_user_meta_data" in sql
    assert "'terms_accepted_at'" in sql
