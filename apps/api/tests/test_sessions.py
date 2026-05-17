"""Tests for the Supabase-backed lesson-session endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_supabase_mock(insert_rows: list[dict[str, Any]] | None = None,
                        select_rows: list[dict[str, Any]] | None = None) -> MagicMock:
    select_chain = MagicMock(name="select-chain")
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.order.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=list(select_rows or []))

    insert_chain = MagicMock(name="insert-chain")
    insert_chain.execute.return_value = MagicMock(data=list(insert_rows or []))

    table = MagicMock()
    table.select.return_value = select_chain
    table.insert.return_value = insert_chain

    client = MagicMock(name="supabase")
    client.table.return_value = table
    client._select = select_chain
    client._insert = insert_chain
    client._table = table
    return client


# ─── POST /sessions ───────────────────────────────────────────────────────
def test_start_session_dev_fallback(
    client: Any, dev_headers: dict[str, str]
) -> None:
    r = client.post(
        "/v1/sessions",
        json={"topic_id": "11111111-1111-1111-1111-111111111111"},
        headers=dev_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["topic_id"] == "11111111-1111-1111-1111-111111111111"
    assert "id" in body


def test_start_session_inserts_into_supabase(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inserted = {
        "id": "55555555-5555-5555-5555-555555555555",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": "11111111-1111-1111-1111-111111111111",
        "started_at": "2026-05-14T00:00:00+00:00",
        "ended_at": None,
        "agent_state": {},
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock(insert_rows=[inserted])
    monkeypatch.setattr("app.api.v1.sessions.get_supabase", lambda: sb)

    r = client.post(
        "/v1/sessions",
        json={"topic_id": "11111111-1111-1111-1111-111111111111"},
        headers=dev_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "55555555-5555-5555-5555-555555555555"

    # Verify table + payload. `assert_any_call` (not `assert_called_with`)
    # because session start now also touches topics/units/courses to
    # lazily enrol the student in a teacher course (task 4.3).
    sb.table.assert_any_call("lesson_sessions")
    insert_payload = sb._table.insert.call_args.args[0]
    assert insert_payload["user_id"] == dev_headers["X-Dev-User-Id"]
    assert insert_payload["topic_id"] == "11111111-1111-1111-1111-111111111111"
    assert insert_payload["agent_state"] == {}


# ─── GET /sessions/{id} ───────────────────────────────────────────────────
def test_get_session_returns_supabase_row(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {
        "id": "66666666-6666-6666-6666-666666666666",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": "77777777-7777-7777-7777-777777777777",
        "started_at": "2026-05-14T00:00:00+00:00",
        "ended_at": None,
        "agent_state": {"step_idx": 3},
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock(select_rows=[row])
    monkeypatch.setattr("app.api.v1.sessions.get_supabase", lambda: sb)

    r = client.get(
        "/v1/sessions/66666666-6666-6666-6666-666666666666", headers=dev_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "66666666-6666-6666-6666-666666666666"

    # Filtered by both id AND user_id (RLS-equivalent enforcement).
    eq_calls = [c.args for c in sb._select.eq.call_args_list]
    assert ("id", "66666666-6666-6666-6666-666666666666") in eq_calls
    assert ("user_id", dev_headers["X-Dev-User-Id"]) in eq_calls


def test_get_session_returns_404_when_missing(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock(select_rows=[])
    monkeypatch.setattr("app.api.v1.sessions.get_supabase", lambda: sb)
    r = client.get(
        "/v1/sessions/99999999-9999-9999-9999-999999999999", headers=dev_headers
    )
    assert r.status_code == 404
