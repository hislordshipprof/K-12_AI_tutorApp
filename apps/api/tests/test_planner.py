"""Tests for the Supabase-backed planner endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_supabase_mock(
    select_rows: list[dict[str, Any]] | None = None,
    insert_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    select_chain = MagicMock()
    for attr in ("select", "eq", "gte", "lt", "order", "limit"):
        getattr(select_chain, attr).return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=list(select_rows or []))

    insert_chain = MagicMock()
    insert_chain.execute.return_value = MagicMock(data=list(insert_rows or []))

    delete_chain = MagicMock()
    for attr in ("eq", "gte", "lt"):
        getattr(delete_chain, attr).return_value = delete_chain
    delete_chain.execute.return_value = MagicMock(data=[])

    table = MagicMock()
    table.select.return_value = select_chain
    table.insert.return_value = insert_chain
    table.delete.return_value = delete_chain

    client = MagicMock()
    client.table.return_value = table
    client._table = table
    client._select = select_chain
    client._insert = insert_chain
    client._delete = delete_chain
    return client


def test_get_week_dev_fallback(client: Any, dev_headers: dict[str, str]) -> None:
    r = client.get("/v1/planner/week", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert "week_start" in body
    assert len(body["blocks"]) == 5  # stub returns 5 days


def test_get_week_queries_supabase_by_user_and_range(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "user_id": dev_headers["X-Dev-User-Id"],
            "date": "2026-05-11",
            "start_time": "16:00:00",
            "duration_min": 30,
            "kind": "lesson",
            "payload": {"title": "Day 1"},
            "status": "planned",
            "created_at": "2026-05-14T00:00:00+00:00",
        }
    ]
    sb = _build_supabase_mock(select_rows=rows)
    monkeypatch.setattr("app.api.v1.planner.get_supabase", lambda: sb)

    r = client.get("/v1/planner/week", headers=dev_headers)
    assert r.status_code == 200
    assert len(r.json()["blocks"]) == 1

    sb.table.assert_called_with("schedule_blocks")
    # user_id filter applied.
    eq_calls = [c.args for c in sb._select.eq.call_args_list]
    assert ("user_id", dev_headers["X-Dev-User-Id"]) in eq_calls
    # Date range filter applied (gte + lt).
    assert sb._select.gte.called
    assert sb._select.lt.called


def test_regenerate_wipes_and_inserts(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inserted = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "user_id": dev_headers["X-Dev-User-Id"],
            "date": "2026-05-11",
            "start_time": "16:00:00",
            "duration_min": 30,
            "kind": "lesson",
            "payload": {"title": "Day 1 lesson"},
            "status": "planned",
            "created_at": "2026-05-14T00:00:00+00:00",
        }
    ]
    sb = _build_supabase_mock(insert_rows=inserted)
    monkeypatch.setattr("app.api.v1.planner.get_supabase", lambda: sb)

    r = client.post(
        "/v1/planner/regenerate",
        json={"week_start": "2026-05-11"},
        headers=dev_headers,
    )
    assert r.status_code == 200

    # Both delete and insert were invoked on schedule_blocks.
    assert sb._table.delete.called
    assert sb._table.insert.called
    # Insert payload is a list of dicts.
    insert_arg = sb._table.insert.call_args.args[0]
    assert isinstance(insert_arg, list) and len(insert_arg) == 5
    assert all(row["user_id"] == dev_headers["X-Dev-User-Id"] for row in insert_arg)
