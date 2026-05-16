"""Tests for the teacher invite-code flow (task 0.3).

Covers:
  - an admin issues an invite code (`POST /v1/admin/teacher-invites`);
  - a non-admin is 403 on the admin route;
  - redeeming a code sets the caller's `profiles.role` to `'teacher'`;
  - a code that is already redeemed cannot be reused;
  - an unknown code 404s.

Supabase is mocked. The `profiles.role` lookup behind `require_role` and
the redeem handler both go through `get_supabase`, so each test installs a
small builder mock keyed by table name.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ─── mock plumbing ────────────────────────────────────────────────────────
def _select_chain(rows: list[dict[str, Any]]) -> MagicMock:
    chain = MagicMock(name="select")
    for attr in ("select", "eq", "is_", "limit", "order"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


def _write_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """A mock for insert/update chains — every method returns self."""
    chain = MagicMock(name="write")
    for attr in ("insert", "update", "eq", "is_"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=list(rows))
    return chain


def _make_supabase(tables: dict[str, MagicMock]) -> MagicMock:
    """Build a supabase mock that dispatches `.table(name)` to a per-table mock."""
    client = MagicMock(name="supabase")
    client.table.side_effect = lambda name: tables[name]
    return client


def _profiles_role(role: str) -> MagicMock:
    """A `profiles` table mock whose `.select(...).execute()` returns one role row."""
    return _select_chain([{"role": role}])


ADMIN_ID = "00000000-0000-0000-0000-000000000001"


# ─── POST /v1/admin/teacher-invites ───────────────────────────────────────
def test_admin_issues_invite_code(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin-role caller gets a fresh, unredeemed invite code back."""
    issued = {
        "code": "TEACH-ABC234",
        "created_by": ADMIN_ID,
        "redeemed_by": None,
        "redeemed_at": None,
        "created_at": "2026-05-15T00:00:00+00:00",
    }
    invites_tbl = _write_chain([issued])
    sb = _make_supabase(
        {"profiles": _profiles_role("admin"), "teacher_invites": invites_tbl}
    )
    # `require_role` (security.py) and the admin endpoint both call get_supabase.
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.admin.get_supabase", lambda: sb)

    r = client.post("/v1/admin/teacher-invites", headers=dev_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["code"].startswith("TEACH-")
    assert body["redeemed_by"] is None
    # The code was persisted.
    invites_tbl.insert.assert_called_once()
    inserted = invites_tbl.insert.call_args.args[0]
    assert inserted["created_by"] == ADMIN_ID


def test_non_admin_gets_403_on_admin_route(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `student`-role caller is forbidden from the admin invite route."""
    sb = _make_supabase({"profiles": _profiles_role("student")})
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.admin.get_supabase", lambda: sb)

    r = client.post("/v1/admin/teacher-invites", headers=dev_headers)
    assert r.status_code == 403


def test_teacher_role_also_403_on_admin_route(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only `admin` may issue invites — a `teacher` is still 403."""
    sb = _make_supabase({"profiles": _profiles_role("teacher")})
    monkeypatch.setattr("app.core.security.get_supabase", lambda: sb)
    monkeypatch.setattr("app.api.v1.admin.get_supabase", lambda: sb)

    r = client.post("/v1/admin/teacher-invites", headers=dev_headers)
    assert r.status_code == 403


# ─── POST /v1/auth/redeem-teacher-invite ──────────────────────────────────
def test_redeem_sets_role_to_teacher(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redeeming a valid unused code promotes the caller to `teacher`."""
    code = "TEACH-XYZ789"

    invites_tbl = MagicMock(name="teacher_invites")
    # 1. lookup → one unredeemed row.
    lookup = _select_chain([{"code": code, "redeemed_by": None, "redeemed_at": None}])
    # 2. claim update → one row claimed.
    claim = _write_chain([{"code": code, "redeemed_by": dev_headers["X-Dev-User-Id"]}])
    invites_tbl.select.return_value = lookup
    invites_tbl.update.return_value = claim

    profiles_tbl = _write_chain([{"id": dev_headers["X-Dev-User-Id"], "role": "teacher"}])

    sb = _make_supabase({"teacher_invites": invites_tbl, "profiles": profiles_tbl})
    monkeypatch.setattr("app.api.v1.auth.get_supabase", lambda: sb)

    r = client.post(
        "/v1/auth/redeem-teacher-invite", json={"code": code}, headers=dev_headers
    )
    assert r.status_code == 200
    assert r.json()["role"] == "teacher"

    # The profile was updated to teacher...
    profiles_tbl.update.assert_called_once_with({"role": "teacher"})
    # ...and the invite was marked redeemed by this user.
    claimed = invites_tbl.update.call_args.args[0]
    assert claimed["redeemed_by"] == dev_headers["X-Dev-User-Id"]
    assert claimed["redeemed_at"] is not None


def test_redeem_used_code_cannot_be_reused(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A code with `redeemed_by` already set is rejected (409) — no reuse."""
    code = "TEACH-USED11"
    invites_tbl = MagicMock(name="teacher_invites")
    invites_tbl.select.return_value = _select_chain(
        [
            {
                "code": code,
                "redeemed_by": "99999999-9999-9999-9999-999999999999",
                "redeemed_at": "2026-05-15T00:00:00+00:00",
            }
        ]
    )
    sb = _make_supabase({"teacher_invites": invites_tbl})
    monkeypatch.setattr("app.api.v1.auth.get_supabase", lambda: sb)

    r = client.post(
        "/v1/auth/redeem-teacher-invite", json={"code": code}, headers=dev_headers
    )
    assert r.status_code == 409
    # The invite was never updated and no profile was promoted.
    invites_tbl.update.assert_not_called()


def test_redeem_unknown_code_404s(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invite code that does not exist returns a clear 404."""
    invites_tbl = MagicMock(name="teacher_invites")
    invites_tbl.select.return_value = _select_chain([])
    sb = _make_supabase({"teacher_invites": invites_tbl})
    monkeypatch.setattr("app.api.v1.auth.get_supabase", lambda: sb)

    r = client.post(
        "/v1/auth/redeem-teacher-invite",
        json={"code": "TEACH-NOPE99"},
        headers=dev_headers,
    )
    assert r.status_code == 404


def test_redeem_lost_race_is_409(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the conditional claim update matches zero rows (another redeemer
    won the race), the redeem fails 409 rather than silently promoting."""
    code = "TEACH-RACE22"
    invites_tbl = MagicMock(name="teacher_invites")
    invites_tbl.select.return_value = _select_chain(
        [{"code": code, "redeemed_by": None, "redeemed_at": None}]
    )
    # The conditional update claims nothing — someone else got there first.
    invites_tbl.update.return_value = _write_chain([])
    sb = _make_supabase({"teacher_invites": invites_tbl})
    monkeypatch.setattr("app.api.v1.auth.get_supabase", lambda: sb)

    r = client.post(
        "/v1/auth/redeem-teacher-invite", json={"code": code}, headers=dev_headers
    )
    assert r.status_code == 409
